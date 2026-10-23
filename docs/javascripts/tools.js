// Online Modbus tools of the project site: CRC calculator and frame decoder,
// value <-> registers converter (byte orders), address converter.
//
// The maths is pure functions in MBTools (also exported for Node, where
// tools/test_site_tools.js checks it against vectors made with Python's
// struct); the bottom half wires them to the forms on the tool pages. Byte
// orders and names follow the app (core/byteorder.py): A = most significant
// byte; ABCD big-endian, BADC byte swap, CDAB word swap, DCBA little-endian.
(function (root) {
  "use strict";

  // ── hex ───────────────────────────────────────────────────────────────
  function parseHex(text) {
    // "01 03 00 00", "0x01,0x03", "0103 0000" → [1, 3, 0, 0]; null if odd
    var s = String(text).replace(/0x/gi, " ").replace(/[,;:\s]+/g, "");
    if (!s.length || s.length % 2 || /[^0-9a-f]/i.test(s)) return null;
    var out = [];
    for (var i = 0; i < s.length; i += 2) out.push(parseInt(s.substr(i, 2), 16));
    return out;
  }
  function hex(bytes) {
    return bytes.map(function (b) { return (b < 16 ? "0" : "") + b.toString(16).toUpperCase(); }).join(" ");
  }
  function hex16(w) { return ("000" + (w & 0xFFFF).toString(16).toUpperCase()).slice(-4); }

  // ── CRC-16/Modbus (poly 0xA001 reflected, init 0xFFFF) ────────────────
  function crc16(bytes) {
    var crc = 0xFFFF;
    for (var i = 0; i < bytes.length; i++) {
      crc ^= bytes[i];
      for (var k = 0; k < 8; k++) crc = (crc & 1) ? (crc >>> 1) ^ 0xA001 : crc >>> 1;
    }
    return crc;
  }
  function withCrc(bytes) {
    var c = crc16(bytes);
    return bytes.concat([c & 0xFF, c >> 8]);       // low byte first on the wire
  }
  function crcOk(frame) {
    if (frame.length < 4) return false;
    var c = crc16(frame.slice(0, -2));
    return frame[frame.length - 2] === (c & 0xFF) && frame[frame.length - 1] === (c >> 8);
  }

  // ── frame decoder (the common functions) ──────────────────────────────
  var FC = { 1: "Read Coils", 2: "Read Discrete Inputs", 3: "Read Holding Registers",
             4: "Read Input Registers", 5: "Write Single Coil", 6: "Write Single Register",
             15: "Write Multiple Coils", 16: "Write Multiple Registers" };
  var EXC = { 1: "Illegal Function", 2: "Illegal Data Address", 3: "Illegal Data Value",
              4: "Slave Device Failure", 5: "Acknowledge", 6: "Slave Device Busy",
              8: "Memory Parity Error", 10: "Gateway Path Unavailable",
              11: "Gateway Target Device Failed to Respond" };
  function u16(b, i) { return (b[i] << 8) | b[i + 1]; }

  // A frame WITHOUT its CRC → list of [field, value] pairs. Requests and
  // responses of FC 01–06 look alike in places; both readings are given
  // where the length alone cannot tell them apart.
  function decode(body) {
    var out = [];
    if (body.length < 2) return out;
    var sid = body[0], fc = body[1], d = body.slice(2);
    out.push(["slave", sid === 0 ? "0 (broadcast)" : String(sid)]);
    if (fc & 0x80) {
      var code = d[0];
      out.push(["function", (fc & 0x7F) + " — exception"]);
      out.push(["exception", code + (EXC[code] ? " — " + EXC[code] : "")]);
      return out;
    }
    out.push(["function", fc + (FC[fc] ? " — " + FC[fc] : "")]);
    if (fc >= 1 && fc <= 4) {
      if (d.length === 4) {
        out.push(["kind", "request"]);
        out.push(["address", u16(d, 0) + " (0x" + hex16(u16(d, 0)) + ")"]);
        out.push(["count", String(u16(d, 2))]);
      } else if (d.length >= 1 && d[0] === d.length - 1) {
        out.push(["kind", "response"]);
        out.push(["bytes", String(d[0])]);
        if (fc >= 3) {
          var regs = [];
          for (var i = 1; i + 1 < d.length; i += 2) regs.push(hex16(u16(d, i)));
          out.push(["registers", regs.join(" ")]);
        } else {
          var bits = [];
          for (var j = 1; j < d.length; j++)
            for (var b = 0; b < 8; b++) bits.push((d[j] >> b) & 1);
          out.push(["bits", bits.join("")]);
        }
      }
    } else if ((fc === 5 || fc === 6) && d.length === 4) {
      out.push(["kind", "request / echo"]);
      out.push(["address", u16(d, 0) + " (0x" + hex16(u16(d, 0)) + ")"]);
      out.push(["value", fc === 5 ? (u16(d, 2) === 0xFF00 ? "ON (FF00)" : u16(d, 2) === 0 ? "OFF (0000)" : "0x" + hex16(u16(d, 2)))
                                  : u16(d, 2) + " (0x" + hex16(u16(d, 2)) + ")"]);
    } else if (fc === 15 || fc === 16) {
      out.push(["address", u16(d, 0) + " (0x" + hex16(u16(d, 0)) + ")"]);
      out.push(["count", String(u16(d, 2))]);
      if (d.length > 5) {
        out.push(["kind", "request"]);
        if (fc === 16) {
          var w = [];
          for (var k = 5; k + 1 < d.length; k += 2) w.push(hex16(u16(d, k)));
          out.push(["registers", w.join(" ")]);
        }
      } else {
        out.push(["kind", "response"]);
      }
    }
    return out;
  }

  // A frame as typed → what it is. A trailing valid CRC means RTU; a valid
  // MBAP header (protocol 0, length = the rest) means Modbus TCP; anything
  // else is an RTU frame still waiting for its CRC. The CRC test comes first:
  // "01 03 00 00 00 02 C4 0B" also looks like an MBAP header.
  function classify(bytes) {
    if (crcOk(bytes))
      return { kind: "rtu", crc: bytes.slice(-2), fields: decode(bytes.slice(0, -2)) };
    if (bytes.length >= 8 && bytes[2] === 0 && bytes[3] === 0 &&
        u16(bytes, 4) === bytes.length - 6) {
      var fields = [["transaction", String(u16(bytes, 0))],
                    ["protocol", "0 (Modbus)"],
                    ["length", String(u16(bytes, 4))]];
      decode(bytes.slice(6)).forEach(function (f) {
        fields.push(f[0] === "slave" ? ["unit", String(bytes[6])] : f);   // unit 0 is no broadcast in TCP
      });
      return { kind: "tcp", fields: fields };
    }
    return { kind: "raw", fields: decode(bytes) };
  }

  // ── values <-> registers ──────────────────────────────────────────────
  var PERM32 = { ABCD: [0, 1, 2, 3], BADC: [1, 0, 3, 2], CDAB: [2, 3, 0, 1], DCBA: [3, 2, 1, 0] };
  var PERM64 = { ABCD: [0, 1, 2, 3, 4, 5, 6, 7], BADC: [1, 0, 3, 2, 5, 4, 7, 6],
                 CDAB: [6, 7, 4, 5, 2, 3, 0, 1], DCBA: [7, 6, 5, 4, 3, 2, 1, 0] };
  var TYPES = {   // bytes, DataView setter/getter
    INT16:  [2, "setInt16", "getInt16"],   UINT16: [2, "setUint16", "getUint16"],
    INT32:  [4, "setInt32", "getInt32"],   UINT32: [4, "setUint32", "getUint32"],
    FLOAT:  [4, "setFloat32", "getFloat32"],
    INT64:  [8, "setBigInt64", "getBigInt64"], UINT64: [8, "setBigUint64", "getBigUint64"],
    DOUBLE: [8, "setFloat64", "getFloat64"]
  };
  function permute(bytes, order) {
    var p = bytes.length === 2 ? (order === "BA" ? [1, 0] : [0, 1])
          : bytes.length === 4 ? PERM32[order] : PERM64[order];
    return p.map(function (i) { return bytes[i]; });
  }
  function words(bytes) {
    var w = [];
    for (var i = 0; i < bytes.length; i += 2) w.push((bytes[i] << 8) | bytes[i + 1]);
    return w;
  }
  // value (string) → { order: [words] } for every byte order of the type
  function encode(type, text) {
    var t = TYPES[type], n = t[0], dv = new DataView(new ArrayBuffer(n));
    var s = String(text).trim().replace(",", ".");
    if (type === "INT64" || type === "UINT64") dv[t[1]](0, BigInt(s.replace(/\.0*$/, "")));
    else if (type === "FLOAT" || type === "DOUBLE") {
      var f = Number(s);
      if (!isFinite(f) && !/^[-+]?inf/i.test(s) && !/^nan$/i.test(s)) throw new Error("NaN");
      dv[t[1]](0, f);
    } else {
      var v = Number(s);
      if (!Number.isInteger(v)) throw new Error("int");
      var lim = { INT16: [-32768, 32767], UINT16: [0, 65535],
                  INT32: [-2147483648, 2147483647], UINT32: [0, 4294967295] }[type];
      if (v < lim[0] || v > lim[1]) throw new Error("range");
      dv[t[1]](0, v);
    }
    var big = [];
    for (var i = 0; i < n; i++) big.push(dv.getUint8(i));
    var out = {};
    (n === 2 ? ["AB", "BA"] : ["ABCD", "BADC", "CDAB", "DCBA"]).forEach(function (o) {
      out[o] = words(permute(big, o));
    });
    return out;
  }
  // A float32 as people read it: whole values exactly (-107613728, as the app
  // shows them), others as the shortest decimal that reads back as the same
  // float32 (24.6, not 24.600000381469727).
  function shortestF32(v) {
    if (!isFinite(v) || Number.isInteger(v)) return v;   // whole floats are exact
    for (var p = 1; p <= 9; p++) {
      var n = Number(v.toPrecision(p));
      if (Math.fround(n) === v) return n;
    }
    return v;
  }
  // registers (list of 16-bit words, as received) → value per byte order
  function decodeWords(type, regs) {
    var t = TYPES[type], n = t[0];
    if (regs.length * 2 !== n) throw new Error("count");
    var wire = [];
    regs.forEach(function (w) { wire.push((w >> 8) & 0xFF, w & 0xFF); });
    var out = {};
    (n === 2 ? ["AB", "BA"] : ["ABCD", "BADC", "CDAB", "DCBA"]).forEach(function (o) {
      var b = permute(wire, o), dv = new DataView(new ArrayBuffer(n));   // involutions
      b.forEach(function (x, i) { dv.setUint8(i, x); });
      var v = dv[t[2]](0);
      out[o] = (type === "FLOAT") ? shortestF32(v) : v;
    });
    return out;
  }
  function parseWords(text, fmt) {
    // fmt "hex": "41C4 CCCD", "0x41C4, 0xCCCD"; "dec": "16836 52429" → [words]
    var parts = String(text).trim().split(/[\s,;]+/).filter(Boolean);
    if (!parts.length) return null;
    var isHex = fmt !== "dec";
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i].replace(/^0x/i, ""), v = isHex ? parseInt(p, 16) : parseInt(p, 10);
      if (isNaN(v) || v < 0 || v > 0xFFFF || (isHex ? /[^0-9a-f]/i.test(p) : /\D/.test(p))) return null;
      out.push(v);
    }
    return out;
  }

  // ── addresses ─────────────────────────────────────────────────────────
  var TABLES = { coil: [0, 1, 5], discrete: [1, 2, null], input: [3, 4, null], holding: [4, 3, 6] };
  // Modicon prefix, read FC, write FC
  // "40001" / "400001" / "30010" / "10001" / "1" (Modicon) → {table, offset}
  function fromModicon(text) {
    var s = String(text).trim();
    if (!/^\d+$/.test(s)) return null;
    var v = parseInt(s, 10), pre, num;
    if (s.length === 6) { pre = Math.floor(v / 100000); num = v % 100000; }
    else if (s.length === 5) { pre = Math.floor(v / 10000); num = v % 10000; }
    else { pre = 0; num = v; }                     // 1…9999 = coil 1…9999
    var table = { 0: "coil", 1: "discrete", 3: "input", 4: "holding" }[pre];
    if (!table || num < 1 || num - 1 > 0xFFFF) return null;
    return { table: table, offset: num - 1 };
  }
  function toModicon(table, offset) {
    var pre = TABLES[table][0], num = offset + 1;
    var five = num <= 9999 ? String(pre) + ("0000" + num).slice(-4) : null;
    var six = String(pre) + ("00000" + num).slice(-5);
    return { five: five, six: six };
  }
  function parseOffset(text) {
    var s = String(text).trim().toLowerCase().replace(/\s+/g, "");
    var v;
    if (/^(0x|\$)[0-9a-f]+$/.test(s)) v = parseInt(s.replace(/^(0x|\$)/, ""), 16);
    else if (/^[0-9a-f]+h$/.test(s)) v = parseInt(s.slice(0, -1), 16);
    else if (/^\d+$/.test(s)) v = parseInt(s, 10);
    else return null;
    return v >= 0 && v <= 0xFFFF ? v : null;
  }

  var MBTools = { parseHex: parseHex, hex: hex, hex16: hex16, crc16: crc16, withCrc: withCrc,
                  crcOk: crcOk, decode: decode, classify: classify, encode: encode, decodeWords: decodeWords,
                  parseWords: parseWords, fromModicon: fromModicon, toModicon: toModicon,
                  parseOffset: parseOffset, TABLES: TABLES };
  if (typeof module !== "undefined" && module.exports) { module.exports = MBTools; return; }
  root.MBTools = MBTools;

  // ══ the forms ═════════════════════════════════════════════════════════
  var EN = (document.documentElement.lang || "ru").slice(0, 2) === "en";
  var T = EN ? {
    badHex: "Not valid hex: two digits per byte, e.g. 01 03 00 00 00 02.",
    crc: "CRC", crcValid: "valid ✓", frame: "Frame with CRC", wire: "on the wire (low byte first)",
    hasCrc: "The last two bytes are a valid CRC — the frame decoded without them:",
    isTcp: "A Modbus TCP frame (MBAP header) — it carries no CRC:",
    transaction: "Transaction ID", protocol: "Protocol", length: "Length", unit: "Unit ID",
    slave: "Device address", "function": "Function", exception: "Exception", kind: "Kind",
    address: "Address", count: "Count", bytes: "Byte count", registers: "Registers",
    bits: "Bits (first bit first)", value: "Value",
    badValue: "Not a valid value for this type.", badRegs: "Enter the registers as hex (41C4 CCCD) or decimal.",
    needRegs: "This type takes %d registers.", order: "Byte order", regsCol: "Registers",
    valueCol: "Value", badAddr: "Enter an address: 40001, 30010, 0x0010, 10h or 16.",
    table: "Table", zero: "Address in the frame (zero-based)", one: "Register number (one-based)",
    modicon: "Modicon notation", read: "Read with", write: "Write with", none: "read-only",
    tables: { coil: "Coils (0x)", discrete: "Discrete inputs (1x)", input: "Input registers (3x)", holding: "Holding registers (4x)" },
    inApp: "In ModbusReader", tooBig: "above 9999 — only the 6-digit form"
  } : {
    badHex: "Это не hex: по две цифры на байт, например 01 03 00 00 00 02.",
    crc: "CRC", crcValid: "верный ✓", frame: "Кадр с CRC", wire: "в кадре (младший байт первым)",
    hasCrc: "Последние два байта — верный CRC; кадр разобран без них:",
    isTcp: "Кадр Modbus TCP (заголовок MBAP) — CRC в нём нет:",
    transaction: "Номер транзакции", protocol: "Протокол", length: "Длина", unit: "Unit ID",
    slave: "Адрес прибора", "function": "Функция", exception: "Исключение", kind: "Тип",
    address: "Адрес", count: "Количество", bytes: "Число байт", registers: "Регистры",
    bits: "Биты (первый бит слева)", value: "Значение",
    badValue: "Это значение не подходит для выбранного типа.", badRegs: "Введите регистры в hex (41C4 CCCD) или десятичными.",
    needRegs: "Этот тип занимает регистров: %d.", order: "Порядок байт", regsCol: "Регистры",
    valueCol: "Значение", badAddr: "Введите адрес: 40001, 30010, 0x0010, 10h или 16.",
    table: "Таблица", zero: "Адрес в кадре (с нуля)", one: "Номер регистра (с единицы)",
    modicon: "Нотация Modicon", read: "Чтение", write: "Запись", none: "только чтение",
    tables: { coil: "Coils (0x)", discrete: "Discrete inputs (1x)", input: "Input-регистры (3x)", holding: "Holding-регистры (4x)" },
    inApp: "В ModbusReader", tooBig: "больше 9999 — только шестизначная запись"
  };
  var KIND = EN ? { request: "request", response: "response", "request / echo": "request / echo" }
                : { request: "запрос", response: "ответ", "request / echo": "запрос / эхо" };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function table(rows, head) {
    var h = head ? "<thead><tr>" + head.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") + "</tr></thead>" : "";
    return "<table>" + h + "<tbody>" + rows.map(function (r) {
      return "<tr>" + r.map(function (c, i) { return (i || head ? "<td>" : "<th>") + c + (i || head ? "</td>" : "</th>"); }).join("") + "</tr>";
    }).join("") + "</tbody></table>";
  }
  function code(s) { return "<code>" + esc(s) + "</code>"; }
  function bind(inputs, fn) {
    inputs.forEach(function (el) { if (el) el.addEventListener("input", fn); if (el) el.addEventListener("change", fn); });
    fn();
  }

  function crcForm() {
    var inp = $("mbt-crc-in"), out = $("mbt-crc-out");
    if (!inp) return;
    bind([inp], function () {
      var bytes = parseHex(inp.value);
      if (!inp.value.trim()) { out.innerHTML = ""; return; }
      if (!bytes) { out.innerHTML = "<p>" + esc(T.badHex) + "</p>"; return; }
      var html = "", r = classify(bytes);
      if (r.kind === "rtu") {
        // The frame already ends in its CRC: confirm it, decode the rest.
        html += table([[esc(T.crc), code(hex(r.crc)) + " — " + esc(T.crcValid)]]);
        html += "<p>" + esc(T.hasCrc) + "</p>";
      } else if (r.kind === "tcp") {
        html += "<p>" + esc(T.isTcp) + "</p>";
      } else {
        var c = crc16(bytes);
        html += table([[esc(T.crc), code("0x" + hex16(c)) + " — " + esc(T.wire) + ": " + code(hex([c & 0xFF, c >> 8]))],
                       [esc(T.frame), code(hex(withCrc(bytes)))]]);
      }
      var fields = r.fields;
      if (fields.length) html += table(fields.map(function (f) {
        var v = f[0] === "kind" ? (KIND[f[1]] || f[1]) : f[1];
        return [esc(T[f[0]] || f[0]), code(v)];
      }));
      out.innerHTML = html;
    });
  }

  function valueForm() {
    var type = $("mbt-val-type"), val = $("mbt-val-in"), out = $("mbt-val-out");
    var regs = $("mbt-reg-in"), fmt = $("mbt-reg-fmt"), out2 = $("mbt-reg-out");
    if (!type) return;
    function show() {
      if (val.value.trim()) {
        try {
          var enc = encode(type.value, val.value);
          out.innerHTML = table(Object.keys(enc).map(function (o) {
            return [code(o), code(enc[o].map(hex16).join(" ")), code(enc[o].join(" "))];
          }), [T.order, T.regsCol + " (hex)", T.regsCol + " (dec)"]);
        } catch (e) { out.innerHTML = "<p>" + esc(T.badValue) + "</p>"; }
      } else out.innerHTML = "";
      if (regs.value.trim()) {
        var w = parseWords(regs.value, fmt.value), n = TYPES[type.value][0] / 2;
        if (!w) { out2.innerHTML = "<p>" + esc(T.badRegs) + "</p>"; return; }
        if (w.length !== n) { out2.innerHTML = "<p>" + esc(T.needRegs.replace("%d", n)) + "</p>"; return; }
        var dec = decodeWords(type.value, w);
        out2.innerHTML = table(Object.keys(dec).map(function (o) {
          return [code(o), code(String(dec[o]))];
        }), [T.order, T.valueCol]);
      } else out2.innerHTML = "";
    }
    bind([type, val, regs, fmt], show);
  }

  function addressForm() {
    var inp = $("mbt-addr-in"), tsel = $("mbt-addr-table"), out = $("mbt-addr-out");
    if (!inp) return;
    bind([inp, tsel], function () {
      var s = inp.value.trim();
      if (!s) { out.innerHTML = ""; return; }
      var r = null;
      // A plain 5/6-digit number from 10001 up reads as Modicon; anything
      // else is an offset in the table picked in the list.
      if (/^\d{5,6}$/.test(s) && parseInt(s, 10) >= 10001) r = fromModicon(s);
      if (!r) {
        var off = parseOffset(s);
        if (off !== null) r = { table: tsel.value, offset: off };
      }
      if (!r) { out.innerHTML = "<p>" + esc(T.badAddr) + "</p>"; return; }
      var m = toModicon(r.table, r.offset), t = TABLES[r.table];
      var pref = { coil: "CO ", discrete: "DI ", input: "IR ", holding: "" }[r.table];
      out.innerHTML = table([
        [esc(T.table), esc(T.tables[r.table])],
        [esc(T.zero), code(String(r.offset)) + " · " + code("0x" + hex16(r.offset))],
        [esc(T.one), code(String(r.offset + 1))],
        [esc(T.modicon), (m.five ? code(m.five) + " · " : esc(T.tooBig) + ": ") + code(m.six)],
        [esc(T.read), code("FC " + ("0" + t[1]).slice(-2))],
        [esc(T.write), t[2] ? code("FC " + ("0" + t[2]).slice(-2)) + (r.table === "holding" ? " / " + code("FC 16") : " / " + code("FC 15")) : esc(T.none)],
        [esc(T.inApp), code(pref + "0x" + hex16(r.offset))]
      ]);
    });
  }

  function init() { crcForm(); valueForm(); addressForm(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(typeof window !== "undefined" ? window : this);
