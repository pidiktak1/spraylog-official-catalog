import fs from "node:fs";
import vm from "node:vm";

const inputPath = process.argv[2];
const outputPath = process.argv[3] || inputPath;
if (!inputPath) throw new Error("Usage: node fix_official_encoding.mjs INPUT [OUTPUT]");

const source = fs.readFileSync(inputPath, "utf8");
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context, { filename: inputPath });

const catalogue = context.window.SPRAYLOG_OFFICIAL;
if (!catalogue?.products || !catalogue?.strings) throw new Error("Official catalogue payload not found");

function repairString(value) {
  return value
    .replace(/([\u00a0-\u00ff])\x03/g, (_, character) =>
      String.fromCodePoint(0x300 + character.codePointAt(0)))
    .replace(/\x03([\u0370-\u03ff])/g, "$1")
    .replaceAll("\x03", "")
    .replaceAll("\x13", "-")
    .replaceAll("γιαερασιτεχνικήχρήση", "για ερασιτεχνική χρήση")
    .replaceAll("Ψώρατου San Jose", "Ψώρα του San Jose")
    .replaceAll("Νηματώδειστουγένους", "Νηματώδεις του γένους")
    .replaceAll("Θερινόςπολτός", "Θερινός πολτός")
    .normalize("NFC");
}

let changedStrings = 0;
function repair(value) {
  if (typeof value === "string") {
    const repaired = repairString(value);
    if (repaired !== value) changedStrings += 1;
    return repaired;
  }
  if (Array.isArray(value)) return value.map(repair);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, repair(item)]));
  }
  return value;
}

const repairedCatalogue = repair(catalogue);
repairedCatalogue.encodingRepair = "Historical Greek labels restored from shifted Windows-1253 text";
const serialized = JSON.stringify(repairedCatalogue);
if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(serialized)) {
  throw new Error("Catalogue still contains control characters after encoding repair");
}
fs.writeFileSync(outputPath, `window.SPRAYLOG_OFFICIAL=${JSON.stringify(repairedCatalogue)};\n`, "utf8");
console.log(JSON.stringify({ changedStrings, products: repairedCatalogue.products.length, strings: repairedCatalogue.strings.length }));
