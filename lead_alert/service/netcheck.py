"""
Network self-check and self-repair: can counsellor computers reach this server?

The service answers http://localhost:8787/health even when Windows Firewall
drops every connection from other computers (traffic from the PC to itself is
never filtered). That is exactly how "status ok, 0 counsellors online, nobody
gets popups" happened on 2026-10-06: the office network "Classroom 5G 3" was
classified as **Public**, while the only rule opening port 8787 ("IntelliBI Lead
Alert 8787") covered **Private** networks only.

What this module does (Windows only; elsewhere it reports ok=None):
  * check()   asks Windows (PowerShell, read-only) for the category of every
              connected network, each firewall profile, and the enabled inbound
              ALLOW rules for TCP <port> (alerts) and UDP <discovery_port>
              (LAN discovery), plus program rules for python; decides whether
              other computers can connect on EVERY connected network.
  * repair()  (re)creates the two rules for ALL network types, limited to the
              local subnet and private (RFC 1918) addresses, so the service keeps
              working whichever network the office PC joins. Needs admin rights;
              the scheduled task runs as SYSTEM.
  * run()     check -> repair if needed and allowed -> check again; logs only
              when the verdict changes or fails; result kept in LAST for /health
              and for the "no counsellor online" alert (which then says "server
              not reachable" instead of blaming the counsellors).
  * fingerprint() cheap snapshot of the local IPv4 addresses, polled often so a
              network change triggers an immediate re-check.
"""
from __future__ import annotations

import json
import platform
import subprocess
import time

RULE_TCP = "IntelliBI Lead Alert 8787"
RULE_UDP = "IntelliBI Lead Alert discovery"
# Local subnet + private ranges (+ the 100.64.0.0/10 range used by private-network
# apps such as Tailscale): works on any office Wi-Fi/LAN, never the open internet.
REMOTE = "localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10"
_REQUIRED = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")

_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
function Get-AllowRules($proto, $port) {
  $out = @()
  foreach ($f in @(Get-NetFirewallPortFilter -Protocol $proto | Where-Object { @($_.LocalPort) -contains $port })) {
    $r = $f | Get-NetFirewallRule
    if ($r -and $r.Enabled.ToString() -eq 'True' -and $r.Direction.ToString() -eq 'Inbound' -and $r.Action.ToString() -eq 'Allow') {
      $af = $r | Get-NetFirewallAddressFilter
      $out += [pscustomobject]@{ Name = "$($r.DisplayName)"; Profile = $r.Profile.ToString();
                                 Remote = (@($af.RemoteAddress) -join ','); Kind = 'port' }
    }
  }
  foreach ($a in @(Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '*python*' })) {
    $r = $a | Get-NetFirewallRule
    if ($r -and $r.Enabled.ToString() -eq 'True' -and $r.Direction.ToString() -eq 'Inbound' -and $r.Action.ToString() -eq 'Allow') {
      $pf = $r | Get-NetFirewallPortFilter
      if ($pf.Protocol -in @($proto, 'Any') -and (@($pf.LocalPort) -contains 'Any' -or @($pf.LocalPort) -contains $port)) {
        $af = $r | Get-NetFirewallAddressFilter
        $out += [pscustomobject]@{ Name = "$($r.DisplayName)"; Profile = $r.Profile.ToString();
                                   Remote = (@($af.RemoteAddress) -join ','); Kind = 'program' }
      }
    }
  }
  return ,$out
}
$nets = @(Get-NetConnectionProfile | ForEach-Object {
  [pscustomobject]@{ Name = "$($_.Name)"; Interface = "$($_.InterfaceAlias)"; Category = $_.NetworkCategory.ToString() } })
$profiles = @(Get-NetFirewallProfile | ForEach-Object {
  [pscustomobject]@{ Name = "$($_.Name)"; Enabled = $_.Enabled.ToString();
                     AllowInboundRules = $_.AllowInboundRules.ToString();
                     DefaultInboundAction = $_.DefaultInboundAction.ToString() } })
[pscustomobject]@{ networks = $nets; profiles = $profiles;
                   rules = (Get-AllowRules 'TCP' '__PORT__');
                   udp_rules = (Get-AllowRules 'UDP' '__UDP__') } | ConvertTo-Json -Depth 4 -Compress
"""

_CATEGORY_TO_PROFILE = {"public": "Public", "private": "Private",
                        "domainauthenticated": "Domain", "domain": "Domain"}

LAST = {"ok": None, "checked_at": "", "summary": "not checked yet", "problems": [],
        "warnings": [], "networks": [], "rules": [], "fix": "", "repaired_at": ""}


def fix_command(port: int = 8787) -> str:
    return (f'lead_alert\\deploy\\Fix-Firewall.bat (as administrator), or: '
            f'Set-NetFirewallRule -DisplayName "{RULE_TCP}" -Profile Any '
            f'-RemoteAddress LocalSubnet')


def _list(x):
    return x if isinstance(x, list) else ([x] if x else [])


def _profile_covers(rule_profile: str, fw_profile: str) -> bool:
    rp = (rule_profile or "").lower()
    return rp in ("any", "") or fw_profile.lower() in [p.strip() for p in rp.split(",")]


def scope_ok(remote: str) -> bool:
    """True when a rule's remote-address scope admits every private range
    (any office Wi-Fi/LAN and private-network apps), not just the same subnet."""
    import ipaddress
    entries = [e.strip() for e in str(remote or "").split(",") if e.strip()]
    if not entries or any(e.lower() in ("any", "*") for e in entries):
        return True
    nets = []
    for e in entries:
        try:
            nets.append(ipaddress.ip_network(e, strict=False))
        except ValueError:
            pass                                      # keywords like LocalSubnet
    return all(any(ipaddress.ip_network(r).subnet_of(n) for n in nets if n.version == 4)
               for r in _REQUIRED)


def _blocked_on(nets, prof, rules) -> list:
    """Networks on which the given rules do NOT let other computers in."""
    out = []
    for n in nets:
        cat = str(n.get("Category", ""))
        fwname = _CATEGORY_TO_PROFILE.get(cat.lower(), cat)
        p = prof.get(fwname.lower(), {})
        if str(p.get("Enabled", "True")).lower() == "false":
            continue                                   # firewall off for this profile
        if str(p.get("AllowInboundRules", "True")).lower() == "false":
            out.append((n, fwname, "shields-up"))
            continue
        if str(p.get("DefaultInboundAction", "")).lower() == "allow":
            continue
        if not any(_profile_covers(str(r.get("Profile", "")), fwname) for r in rules):
            out.append((n, fwname, "no-rule"))
    return out


def evaluate(data: dict, port: int = 8787, udp_port: int = 8788) -> dict:
    """Pure decision from the PowerShell data (unit-tested)."""
    nets, profiles = _list(data.get("networks")), _list(data.get("profiles"))
    rules, udp_rules = _list(data.get("rules")), _list(data.get("udp_rules"))
    prof = {str(p.get("Name", "")).lower(): p for p in profiles}
    problems, warnings, repairable = [], [], False
    if not nets:
        problems.append("this computer is not connected to any network")
    for n, fwname, why in _blocked_on(nets, prof, rules):
        label = f'network "{n.get("Name", "?")}" is {n.get("Category")}'
        if why == "shields-up":
            problems.append(f"{label} and the {fwname} firewall profile blocks ALL "
                            f"incoming connections (rules ignored)")
        else:
            repairable = True
            have = ", ".join(f'"{r.get("Name")}" ({r.get("Profile")})' for r in rules) or "none"
            problems.append(f"{label}, but no enabled firewall rule allows TCP {port} on "
                            f"{fwname} networks (rules for port {port}: {have})")
    # Scope: a rule limited to "LocalSubnet" lets in only devices on exactly the
    # same subnet; other office networks / private-network apps would be refused.
    if nets and rules and not problems:
        cats = {_CATEGORY_TO_PROFILE.get(str(n.get("Category", "")).lower(), "") for n in nets}
        covering = [r for r in rules if any(_profile_covers(str(r.get("Profile", "")), c) for c in cats)]
        if covering and not any(scope_ok(r.get("Remote", "")) for r in covering):
            repairable = True
            warnings.append(f"firewall rule for TCP {port} only admits "
                            f"{covering[0].get('Remote') or 'a limited range'} — counsellors on "
                            f"other office networks would be refused (auto-repair widens it to "
                            f"all private addresses)")
    if nets and "udp_rules" in data:
        for n, fwname, why in _blocked_on(nets, prof, udp_rules):
            if why == "no-rule":
                repairable = True
                warnings.append(f'LAN discovery (UDP {udp_port}) blocked on '
                                f'{n.get("Category")} network "{n.get("Name", "?")}" — apps '
                                f'cannot find this server if its address changes')
    ok = not problems
    summary = (f"counsellor computers can reach port {port}" if ok else
               "COUNSELLOR COMPUTERS CANNOT REACH THIS SERVER: " + "; ".join(problems))
    return {"ok": ok, "summary": summary, "problems": problems, "warnings": warnings,
            "repairable": repairable, "networks": nets, "rules": rules,
            "fix": "" if ok else fix_command(port)}


def _powershell(script: str, timeout: int) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                          "Bypass", "-Command", script], capture_output=True, text=True,
                         timeout=timeout, creationflags=flags)
    return out.stdout.strip()


def check(port: int = 8787, udp_port: int = 8788, timeout: int = 90) -> dict:
    if platform.system() != "Windows":
        return {"ok": None, "summary": "not applicable (not Windows)", "problems": [],
                "warnings": [], "repairable": False, "networks": [], "rules": [], "fix": ""}
    try:
        raw = _powershell(_PS.replace("__PORT__", str(port)).replace("__UDP__", str(udp_port)),
                          timeout)
        return evaluate(json.loads(raw or "{}"), port, udp_port)
    except Exception as e:
        return {"ok": None, "summary": f"self-check could not run: {e}", "problems": [],
                "warnings": [], "repairable": False, "networks": [], "rules": [], "fix": ""}


def _netsh(args: list) -> tuple:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run(["netsh", "advfirewall", "firewall"] + args, capture_output=True,
                       text=True, timeout=60, creationflags=flags)
    return p.returncode, (p.stdout + p.stderr).strip()


def repair(port: int = 8787, udp_port: int = 8788) -> tuple:
    """(Re)create both rules for ALL network types, local/private addresses only.
    Returns (ok, message). Requires administrator / SYSTEM."""
    if platform.system() != "Windows":
        return False, "not Windows"
    msgs = []
    for name, proto, p in ((RULE_TCP, "TCP", port), (RULE_UDP, "UDP", udp_port)):
        _netsh(["delete", "rule", f"name={name}"])          # no duplicates / stale scope
        rc, out = _netsh(["add", "rule", f"name={name}", "dir=in", "action=allow",
                          f"protocol={proto}", f"localport={p}", "profile=any",
                          f"remoteip={REMOTE}", "enable=yes"])
        if rc != 0:
            return False, f"could not create rule '{name}': {out} (needs administrator)"
        msgs.append(f"{name} ({proto} {p})")
    return True, "firewall rules set for all network types: " + ", ".join(msgs)


def fingerprint() -> str:
    """Cheap: the set of local IPv4 addresses (changes when the network changes)."""
    try:
        from discovery import local_ipv4s
        return ",".join(local_ipv4s())
    except Exception:
        return ""


def run(port: int = 8787, udp_port: int = 8788, auto_fix: bool = True,
        reason: str = "scheduled") -> dict:
    """Check, repair if needed (and allowed), re-check. Blocking: call from a
    worker thread. Updates LAST and logs on change/failure."""
    res = check(port, udp_port)
    if auto_fix and res.get("repairable"):
        ok, msg = repair(port, udp_port)
        print(f"  [netcheck] AUTO-REPAIR ({reason}): {msg}")
        if ok:
            res = check(port, udp_port)
            res["repaired_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    res["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    res.setdefault("repaired_at", LAST.get("repaired_at", ""))
    changed = (res.get("ok"), res.get("summary"), tuple(res.get("warnings", []))) != \
        (LAST.get("ok"), LAST.get("summary"), tuple(LAST.get("warnings", [])))
    LAST.clear()
    LAST.update(res)
    if changed or res.get("ok") is False:
        tag = "OK" if res.get("ok") else ("PROBLEM" if res.get("ok") is False else "INFO")
        print(f"  [netcheck] {tag} ({reason}): {res['summary']}")
        for w in res.get("warnings", []):
            print(f"  [netcheck] WARNING: {w}")
        if res.get("fix"):
            print(f"  [netcheck] FIX: {res['fix']}")
    return res
