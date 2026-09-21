

// function doPost(e) {
//   try {
//     var spreadsheetId = "1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE";
//     var sheetName = "Contact Us Form";

//     var spreadsheet = SpreadsheetApp.openById(spreadsheetId);
//     var sheet = spreadsheet.getSheetByName(sheetName);

//     // Full set of headers covering the original form + the two new forms
//     var headers = [
//       "Type",
//       "Full Name",
//       "Email Address",
//       "Mobile Number",
//       "Interested Program",
//       "Career Goal",
//       "Current Role",
//       "Year of Graduation",
//       "Preferred Time",
//       "Preferred Consultation Mode",
//       "Background",
//       "WhatsApp Updates",
//       "Message",
//       "Date"
//     ];

//     if (!sheet) {
//       sheet = spreadsheet.insertSheet(sheetName);

//       sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

//       sheet
//         .getRange(1, 1, 1, headers.length)
//         .setFontWeight("bold")
//         .setBackground("#0B57D0")
//         .setFontColor("#FFFFFF");
//     } else {
//       // SAFE top-up: only fills in a header cell (A1:N1) if it is currently
//       // BLANK. It will never overwrite existing header text, so it can't
//       // scramble a live sheet that has manually managed columns (like
//       // "Call Taken By" / "Remark" at O and P) sitting next to it.
//       var existingHeaders = sheet
//         .getRange(1, 1, 1, headers.length)
//         .getValues()[0];

//       headers.forEach(function (header, idx) {
//         if (!existingHeaders[idx] || existingHeaders[idx].toString().trim() === "") {
//           sheet.getRange(1, idx + 1).setValue(header);
//           sheet
//             .getRange(1, idx + 1)
//             .setFontWeight("bold")
//             .setBackground("#0B57D0")
//             .setFontColor("#FFFFFF");
//         }
//       });
//     }

//     // NOTE: this script only ever reads/writes columns A:N (the 14 headers
//     // above). Columns O ("Call Taken By") and P ("Remark") are managed
//     // manually by your team and are never touched by appendRow below.

//     if (!e || !e.postData || !e.postData.contents) {
//       throw new Error("No POST data received");
//     }

//     Logger.log("Raw POST data: " + e.postData.contents);

//     var data = JSON.parse(e.postData.contents);

//     // "Type" is sent by you from the frontend to identify which form the
//     // submission came from (e.g. "Alumni 1:1", "Program Enquiry", "Data & AI Journey")
//     var type = data.type || data.formType || "";

//     var fullName = data.fullName || data.name || "";
//     var email = data.email || data.emailAddress || "";
//     var mobile =
//       data.mobile ||
//       data.mobileNumber ||
//       data.phoneNumber ||
//       "";

//     var interestedProgram =
//       data.interestedProgram ||
//       data.program ||
//       data.courseInterested ||
//       data.course ||
//       data.topicOfInterest ||
//       "";

//     var careerGoal = data.careerGoal || "";

//     var currentRole =
//       data.currentRole ||
//       data.current_role ||
//       data.currentJobRole ||
//       data.jobRole ||
//       data.currentDesignation ||
//       "";

//     var yearOfGraduation =
//       data.yearOfGraduation ||
//       data.graduationYear ||
//       "";

//     var preferredTime =
//       data.preferredTime ||
//       data.slot ||
//       "";

//     var preferredConsultationMode =
//       data.preferredConsultationMode ||
//       data.consultationMode ||
//       "";

//     var background = data.background || data.yourBackground || "";

//     var whatsappRaw =
//       data.whatsappUpdates !== undefined
//         ? data.whatsappUpdates
//         : data.whatsapp;
//     var whatsappUpdates =
//       whatsappRaw === true || whatsappRaw === "true"
//         ? "Yes"
//         : whatsappRaw === false || whatsappRaw === "false" || whatsappRaw === undefined
//         ? ""
//         : whatsappRaw;

//     var message =
//       data.message ||
//       data.yourMessage ||
//       data.userMessage ||
//       "";

//     if (!fullName || !mobile) {
//       throw new Error("Missing required fields: fullName and mobile");
//     }

//     var currentDate = Utilities.formatDate(
//       new Date(),
//       Session.getScriptTimeZone(),
//       "dd/MM/yyyy HH:mm:ss"
//     );

//     sheet.appendRow([
//       type,
//       fullName,
//       email,
//       mobile,
//       interestedProgram,
//       careerGoal,
//       currentRole,
//       yearOfGraduation,
//       preferredTime,
//       preferredConsultationMode,
//       background,
//       whatsappUpdates,
//       message,
//       currentDate
//     ]);

//     sendAdminNotification(
//       type,
//       fullName,
//       mobile,
//       email,
//       interestedProgram,
//       careerGoal,
//       preferredTime,
//       preferredConsultationMode,
//       background,
//       currentRole,
//       yearOfGraduation,
//       whatsappUpdates,
//       message,
//       currentDate
//     );

//     return ContentService
//       .createTextOutput(JSON.stringify({
//         status: "success",
//         message: "Form submitted successfully",
//         timestamp: currentDate
//       }))
//       .setMimeType(ContentService.MimeType.JSON);

//   } catch (error) {
//     Logger.log("Error in doPost: " + error);

//     return ContentService
//       .createTextOutput(JSON.stringify({
//         status: "error",
//         message: error.toString()
//       }))
//       .setMimeType(ContentService.MimeType.JSON);
//   }
// }

// function doGet(e) {
//   return ContentService
//     .createTextOutput(JSON.stringify({
//       status: "active",
//       message: "IntelliBi Program Enquiry API is running",
//       sheetName: "Contact Us Form",
//       requiredFields: ["fullName", "mobile"],
//       optionalFields: [
//         "type",
//         "email",
//         "interestedProgram",
//         "careerGoal",
//         "currentRole",
//         "yearOfGraduation",
//         "preferredTime",
//         "preferredConsultationMode",
//         "background",
//         "whatsappUpdates",
//         "message"
//       ],
//       timestamp: new Date().toISOString()
//     }))
//     .setMimeType(ContentService.MimeType.JSON);
// }


// function sendAdminNotification(
//   type,
//   fullName,
//   mobile,
//   email,
//   interestedProgram,
//   careerGoal,
//   preferredTime,
//   preferredConsultationMode,
//   background,
//   currentRole,
//   yearOfGraduation,
//   whatsappUpdates,
//   message,
//   timestamp
// ) {
//   try {

//     var adminEmail = "intellibiinnovationtechnologie@gmail.com,salesintellibi@gmail.com,info@intellibiinnovationstechnologies.in";
// // "intellibiinnovationtechnologie@gmail.com,salesintellibi@gmail.com,info@intellibiinnovationstechnologies.in"
// //hiteshadbanao@gmail.com,missnehaladbanao@gmail.com,lokesh.accucia@gmail.com
//     var sheetUrl =
//       "https://docs.google.com/spreadsheets/d/1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE";

//     var subject = type
//       ? "🎯 New " + type + " Enquiry Received"
//       : "🎯 New Program Enquiry Received";

//     function createRow(label, value) {
//       if (!value || value.toString().trim() === "") {
//         return "";
//       }

//       return `
//       <tr>
//         <td style="
//           padding:14px;
//           font-weight:600;
//           color:#374151;
//           border-bottom:1px solid #E5E7EB;
//           width:35%;
//         ">
//           ${label}
//         </td>

//         <td style="
//           padding:14px;
//           color:#111827;
//           border-bottom:1px solid #E5E7EB;
//         ">
//           ${value}
//         </td>
//       </tr>
//       `;
//     }

//     var htmlBody = `
//     <div style="
//       background:#F4F7FB;
//       padding:30px;
//       font-family:Arial,sans-serif;
//     ">

//       <div style="
//         max-width:700px;
//         margin:auto;
//         background:#FFFFFF;
//         border-radius:12px;
//         overflow:hidden;
//         box-shadow:0 2px 10px rgba(0,0,0,0.1);
//       ">

//         <div style="
//           background:linear-gradient(135deg,#0B57D0,#1E88E5);
//           padding:30px;
//           text-align:center;
//         ">
//           <h1 style="
//             margin:0;
//             color:#FFFFFF;
//             font-size:28px;
//           ">
//             New Program Enquiry
//           </h1>

//           <p style="
//             color:#E8F0FE;
//             margin-top:10px;
//           ">
//             ${type ? type : "IntelliBi Program Enquiry Form"}
//           </p>
//         </div>

//         <div style="padding:30px;">

//           <div style="
//             background:#EEF6FF;
//             border-left:5px solid #0B57D0;
//             padding:15px;
//             border-radius:6px;
//             margin-bottom:25px;
//           ">
//             <strong style="color:#0B57D0;">
//               A new enquiry has been received from the website.
//             </strong>
//           </div>

//           <table style="
//             width:100%;
//             border-collapse:collapse;
//           ">
//             ${createRow("Type", type)}
//             ${createRow("Full Name", fullName)}
//             ${createRow("Email Address", email)}
//             ${createRow("Mobile Number", mobile)}
//             ${createRow("Interested Program", interestedProgram)}
//             ${createRow("Career Goal", careerGoal)}
//             ${createRow("Current Role", currentRole)}
//             ${createRow("Year of Graduation", yearOfGraduation)}
//             ${createRow("Preferred Time", preferredTime)}
//             ${createRow("Preferred Consultation Mode", preferredConsultationMode)}
//             ${createRow("Background", background)}
//             ${createRow("WhatsApp Updates", whatsappUpdates)}
//             ${createRow("Submitted On", timestamp)}
//           </table>

//           ${
//             message && message.trim()
//               ? `
//             <div style="
//               margin-top:25px;
//               background:#FFF8E1;
//               border-left:5px solid #FFC107;
//               padding:18px;
//               border-radius:6px;
//             ">
//               <h3 style="
//                 margin-top:0;
//                 color:#B26A00;
//               ">
//                 Message
//               </h3>

//               <p style="
//                 margin:0;
//                 color:#5F4B00;
//                 white-space:pre-wrap;
//               ">
//                 ${message}
//               </p>
//             </div>
//           `
//               : ""
//           }

//           <div style="
//             text-align:center;
//             margin-top:35px;
//           ">
//             <a href="${sheetUrl}"
//                style="
//                  background:#0B57D0;
//                  color:#FFFFFF;
//                  padding:14px 30px;
//                  text-decoration:none;
//                  border-radius:8px;
//                  font-weight:bold;
//                  display:inline-block;
//                ">
//                View Lead Sheet
//             </a>
//           </div>

//         </div>

//         <div style="
//           background:#F9FAFB;
//           padding:18px;
//           text-align:center;
//           color:#6B7280;
//           font-size:12px;
//         ">
//           This is an automated notification generated from the IntelliBi Program Enquiry Form.
//         </div>

//       </div>

//     </div>
//     `;

//     var plainBody = `
// NEW PROGRAM ENQUIRY

// ${type ? "Type: " + type : ""}
// ${fullName ? "Full Name: " + fullName : ""}
// ${email ? "Email Address: " + email : ""}
// ${mobile ? "Mobile Number: " + mobile : ""}
// ${interestedProgram ? "Interested Program: " + interestedProgram : ""}
// ${careerGoal ? "Career Goal: " + careerGoal : ""}
// ${currentRole ? "Current Role: " + currentRole : ""}
// ${yearOfGraduation ? "Year of Graduation: " + yearOfGraduation : ""}
// ${preferredTime ? "Preferred Time: " + preferredTime : ""}
// ${preferredConsultationMode ? "Preferred Consultation Mode: " + preferredConsultationMode : ""}
// ${background ? "Background: " + background : ""}
// ${whatsappUpdates ? "WhatsApp Updates: " + whatsappUpdates : ""}
// ${timestamp ? "Submitted On: " + timestamp : ""}

// ${message ? "\nMessage:\n" + message : ""}

// Lead Sheet:
// ${sheetUrl}
// `;

//     MailApp.sendEmail({
//       to: adminEmail,
//       subject: subject,
//       body: plainBody,
//       htmlBody: htmlBody
//     });

//     Logger.log("Admin notification email sent successfully");

//   } catch (error) {
//     Logger.log("Error sending admin email: " + error);
//   }
// }


/**
 * Canonicalise a mobile number to the same 10-digit national format used across
 * the rest of the IntelliBI system (the Consolidate master and all reports store
 * the last 10 digits). Strips spaces, "+", dashes, brackets and any country code
 * (e.g. leading "91" or "0"), keeping the final 10 digits. Returns "" for blanks.
 * Generic — no per-record special cases.
 */
function normalizeMobile_(value) {
  if (value === null || value === undefined) return "";
  var digits = String(value).replace(/\D/g, "");   // keep digits only (drops +, spaces, etc.)
  if (digits.length >= 10) {
    digits = digits.slice(-10);                     // last 10 = national number (drops 91 / 0 / country code)
  }
  return digits;
}

function doPost(e) {
  try {
    var spreadsheetId = "1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE";
    var sheetName = "Contact Us Form";

    var spreadsheet = SpreadsheetApp.openById(spreadsheetId);
    var sheet = spreadsheet.getSheetByName(sheetName);

    // Updated headers as per your new Google Sheet sequence A:N
    var headers = [
      "Enquiry Date",
      "Full Name",
      "Mobile Number",
      "Email ID",
      "Current Role",
      "Preferred Time",
      "Course Interested In",
      "Career Goal",
      "Total Experience",
      "Preferred Consultation Mode",
      "Candidate Type",
      "Candidate Message",
      "WhatsApp Updates",
      "Form Type"
    ];

    if (!sheet) {
      sheet = spreadsheet.insertSheet(sheetName);
    }

    // Keep columns A:N exactly matching the new header sequence.
    // This does not touch columns after N, such as Call Taken By / Remark.
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

    sheet
      .getRange(1, 1, 1, headers.length)
      .setFontWeight("bold")
      .setBackground("#0B57D0")
      .setFontColor("#FFFFFF");

    if (!e || !e.postData || !e.postData.contents) {
      throw new Error("No POST data received");
    }

    Logger.log("Raw POST data: " + e.postData.contents);

    var data = JSON.parse(e.postData.contents);

    var formType = data.formType || data.type || "";

    var fullName = data.fullName || data.name || "";

    var mobile =
      data.mobile ||
      data.mobileNumber ||
      data.phoneNumber ||
      "";
    // Cleanse to the canonical 10-digit form the rest of the system uses, so the
    // Mobile Number is stored consistently (no country code, no "+"/spaces, and
    // never as a number/float). Applies to the sheet, the notification e-mail and
    // the required-field check below.
    mobile = normalizeMobile_(mobile);

    var email =
      data.email ||
      data.emailAddress ||
      data.emailId ||
      "";

    var currentRole =
      data.currentRole ||
      data.current_role ||
      data.currentJobRole ||
      data.jobRole ||
      data.currentDesignation ||
      "";

    var preferredTime =
      data.preferredTime ||
      data.slot ||
      "";

    var courseInterestedIn =
      data.courseInterestedIn ||
      data.courseInterested ||
      data.interestedProgram ||
      data.program ||
      data.course ||
      data.topicOfInterest ||
      "";

    var careerGoal = data.careerGoal || "";

    var totalExperience =
      data.totalExperience ||
      data.experience ||
      data.yearOfGraduation ||
      data.graduationYear ||
      "";

    var preferredConsultationMode =
      data.preferredConsultationMode ||
      data.consultationMode ||
      "";

    var candidateType =
      data.candidateType ||
      data.background ||
      data.yourBackground ||
      "";

    var candidateMessage =
      data.candidateMessage ||
      data.message ||
      data.yourMessage ||
      data.userMessage ||
      "";

    var whatsappRaw =
      data.whatsappUpdates !== undefined
        ? data.whatsappUpdates
        : data.whatsapp;

    var whatsappUpdates =
      whatsappRaw === true || whatsappRaw === "true"
        ? "Yes"
        : whatsappRaw === false || whatsappRaw === "false" || whatsappRaw === undefined
        ? ""
        : whatsappRaw;

    if (!fullName || !mobile) {
      throw new Error("Missing required fields: fullName and mobile");
    }

    var enquiryDate = Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone(),
      "dd/MM/yyyy HH:mm:ss"
    );

    // New append order exactly matching your sheet:
    // A Date, B Name, C Mobile, D Email, E Role, F Time, G Course,
    // H Goal, I Experience, J Mode, K Candidate Type, L Message,
    // M WhatsApp, N Form Type
    sheet.appendRow([
      enquiryDate,
      fullName,
      mobile,
      email,
      currentRole,
      preferredTime,
      courseInterestedIn,
      careerGoal,
      totalExperience,
      preferredConsultationMode,
      candidateType,
      candidateMessage,
      whatsappUpdates,
      formType
    ]);

    // Store the Mobile Number (column C) as TEXT so Sheets never converts the
    // digits to a number/float (which dropped precision and produced the ".0"
    // artefacts). Value is the already-normalised 10-digit number.
    var _mobRange = sheet.getRange(sheet.getLastRow(), 3);
    _mobRange.setNumberFormat("@");
    _mobRange.setValue(mobile);

    sendAdminNotification(
      enquiryDate,
      fullName,
      mobile,
      email,
      currentRole,
      preferredTime,
      courseInterestedIn,
      careerGoal,
      totalExperience,
      preferredConsultationMode,
      candidateType,
      candidateMessage,
      whatsappUpdates,
      formType
    );

    return ContentService
      .createTextOutput(JSON.stringify({
        status: "success",
        message: "Form submitted successfully",
        timestamp: enquiryDate
      }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    Logger.log("Error in doPost: " + error);

    return ContentService
      .createTextOutput(JSON.stringify({
        status: "error",
        message: error.toString()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({
      status: "active",
      message: "IntelliBi Program Enquiry API is running",
      sheetName: "Contact Us Form",
      requiredFields: ["fullName", "mobile"],
      optionalFields: [
        "formType",
        "email",
        "currentRole",
        "preferredTime",
        "courseInterestedIn",
        "careerGoal",
        "totalExperience",
        "preferredConsultationMode",
        "candidateType",
        "candidateMessage",
        "whatsappUpdates"
      ],
      timestamp: new Date().toISOString()
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

function sendAdminNotification(
  enquiryDate,
  fullName,
  mobile,
  email,
  currentRole,
  preferredTime,
  courseInterestedIn,
  careerGoal,
  totalExperience,
  preferredConsultationMode,
  candidateType,
  candidateMessage,
  whatsappUpdates,
  formType
) {
  try {
    var adminEmail = "intellibi_sales_team@googlegroups.com";
    // Previous individual recipients (kept for reference / easy revert):
    // "intellibiinnovationtechnologie@gmail.com,salesintellibi@gmail.com,info@intellibiinnovationstechnologies.in"

    var sheetUrl =
      "https://docs.google.com/spreadsheets/d/1prW3GKMnGJZ2U5b0gKjLqTJfczfFTYxUwmWImneDtnE";

    var subject = formType
      ? "New " + formType + " Enquiry Received"
      : "New Program Enquiry Received";

    function createRow(label, value) {
      if (!value || value.toString().trim() === "") {
        return "";
      }

      return `
      <tr>
        <td style="
          padding:14px;
          font-weight:600;
          color:#374151;
          border-bottom:1px solid #E5E7EB;
          width:35%;
        ">
          ${label}
        </td>

        <td style="
          padding:14px;
          color:#111827;
          border-bottom:1px solid #E5E7EB;
        ">
          ${value}
        </td>
      </tr>
      `;
    }

    var htmlBody = `
    <div style="
      background:#F4F7FB;
      padding:30px;
      font-family:Arial,sans-serif;
    ">

      <div style="
        max-width:700px;
        margin:auto;
        background:#FFFFFF;
        border-radius:12px;
        overflow:hidden;
        box-shadow:0 2px 10px rgba(0,0,0,0.1);
      ">

        <div style="
          background:linear-gradient(135deg,#0B57D0,#1E88E5);
          padding:30px;
          text-align:center;
        ">
          <h1 style="
            margin:0;
            color:#FFFFFF;
            font-size:28px;
          ">
            New Program Enquiry
          </h1>

          <p style="
            color:#E8F0FE;
            margin-top:10px;
          ">
            ${formType ? formType : "IntelliBi Program Enquiry Form"}
          </p>
        </div>

        <div style="padding:30px;">

          <div style="
            background:#EEF6FF;
            border-left:5px solid #0B57D0;
            padding:15px;
            border-radius:6px;
            margin-bottom:25px;
          ">
            <strong style="color:#0B57D0;">
              A new enquiry has been received from the website.
            </strong>
          </div>

          <table style="
            width:100%;
            border-collapse:collapse;
          ">
            ${createRow("Enquiry Date", enquiryDate)}
            ${createRow("Full Name", fullName)}
            ${createRow("Mobile Number", mobile)}
            ${createRow("Email ID", email)}
            ${createRow("Current Role", currentRole)}
            ${createRow("Preferred Time", preferredTime)}
            ${createRow("Course Interested In", courseInterestedIn)}
            ${createRow("Career Goal", careerGoal)}
            ${createRow("Total Experience", totalExperience)}
            ${createRow("Preferred Consultation Mode", preferredConsultationMode)}
            ${createRow("Candidate Type", candidateType)}
            ${createRow("WhatsApp Updates", whatsappUpdates)}
            ${createRow("Form Type", formType)}
          </table>

          ${
            candidateMessage && candidateMessage.trim()
              ? `
            <div style="
              margin-top:25px;
              background:#FFF8E1;
              border-left:5px solid #FFC107;
              padding:18px;
              border-radius:6px;
            ">
              <h3 style="
                margin-top:0;
                color:#B26A00;
              ">
                Candidate Message
              </h3>

              <p style="
                margin:0;
                color:#5F4B00;
                white-space:pre-wrap;
              ">
                ${candidateMessage}
              </p>
            </div>
          `
              : ""
          }

          <div style="
            text-align:center;
            margin-top:35px;
          ">
            <a href="${sheetUrl}"
               style="
                 background:#0B57D0;
                 color:#FFFFFF;
                 padding:14px 30px;
                 text-decoration:none;
                 border-radius:8px;
                 font-weight:bold;
                 display:inline-block;
               ">
               View Lead Sheet
            </a>
          </div>

        </div>

        <div style="
          background:#F9FAFB;
          padding:18px;
          text-align:center;
          color:#6B7280;
          font-size:12px;
        ">
          This is an automated notification generated from the IntelliBi Program Enquiry Form.
        </div>

      </div>

    </div>
    `;

    var plainBody = `
NEW PROGRAM ENQUIRY

${enquiryDate ? "Enquiry Date: " + enquiryDate : ""}
${fullName ? "Full Name: " + fullName : ""}
${mobile ? "Mobile Number: " + mobile : ""}
${email ? "Email ID: " + email : ""}
${currentRole ? "Current Role: " + currentRole : ""}
${preferredTime ? "Preferred Time: " + preferredTime : ""}
${courseInterestedIn ? "Course Interested In: " + courseInterestedIn : ""}
${careerGoal ? "Career Goal: " + careerGoal : ""}
${totalExperience ? "Total Experience: " + totalExperience : ""}
${preferredConsultationMode ? "Preferred Consultation Mode: " + preferredConsultationMode : ""}
${candidateType ? "Candidate Type: " + candidateType : ""}
${whatsappUpdates ? "WhatsApp Updates: " + whatsappUpdates : ""}
${formType ? "Form Type: " + formType : ""}

${candidateMessage ? "\nCandidate Message:\n" + candidateMessage : ""}

Lead Sheet:
${sheetUrl}
`;

    MailApp.sendEmail({
      to: adminEmail,
      subject: subject,
      body: plainBody,
      htmlBody: htmlBody
    });

    Logger.log("Admin notification email sent successfully");

  } catch (error) {
    Logger.log("Error sending admin email: " + error);
  }
}




