"""
TFT EAS 911 -> character-generator adapter   (MicroPython for Raspberry Pi Pico / RP2040)
===========================================================================================
Save this file on the Pico as  main.py  so it starts automatically at power-up.
Watch the output in Thonny's shell (or any USB serial terminal) to see everything it does.

WHAT IT DOES
  The EAS 911's COM2 port (J302) talks to an external "video character generator" using
  the protocol in Appendix E of the EAS 911 manual.  This script plays the part of that
  character generator.  For every alert the 911 receives, it:
    1. accepts the "message ready" notice (which contains the raw EAS header),
    2. requests and receives the plain-English translation of the alert,
    3. optionally completes the audio/EOM handshake so the 911 finishes cleanly,
    4. logs everything to the console and hands the text to deliver().

PROTOCOL SUMMARY  (RS-232, 9600 baud, 8-N-1)
  Every message is:  STX (0x02) + control byte + optional data + ETX (0x03)
    0x04 audio header + attention tone   0x05 alert voice + audio EOM   0x06 header translation
    0x07 "message ready" (911 -> CG)     0x08 last text message         0x09 user announcement
    0x0A alert voice only                0x0B exception / abort
  Normal sequence (who sends what):
    911 -> us : STX 07 <EAS header> ETX    "I have a message" (repeats up to 3x, 2 s apart)
    us  -> 911: STX 06 ETX                 "send me the translation"
    911 -> us : STX 06 <text> ETX          the plain-English alert text
    us  -> 911: STX 04 ETX   911 -> us: STX 04 ETX    request / acknowledge audio header
    us  -> 911: STX 05 ETX   911 -> us: STX 05 ETX    request / acknowledge voice + EOM
  If we never answer the "message ready" frame the 911 gives up and aborts the message.
  The 911 does not talk to the CG while in PRACTICE mode.  Menu item 18 on the 911
  ("ENABLE CHAR GEN INTERFACE") must be turned on.

WIRING  (Pico UART is 3.3 V logic; the 911 is RS-232, so a 3.3 V MAX3232/SP3232 is REQUIRED)
  Pico GP0 (TX)  -> MAX3232 T1IN         Pico GP1 (RX)  <- MAX3232 R1OUT
  Pico 3V3 -> MAX3232 VCC                Pico GND -> MAX3232 GND
  MAX3232 DB9 -> EAS 911 J302:  pin 2 = 911 Rx, pin 3 = 911 Tx, pin 5 = GND
  If no data arrives, swap TX and RX (null-modem).
  Output to a Horita SCT-50 (optional, UART1):
    Pico GP4 (UART1 TX) -> second MAX3232 channel T2IN;  Pico GP5 (UART1 RX) <- R2OUT (not required)
    MAX3232 channel-2 DB9 -> SCT-50 SERIAL IN (DB9 female) wired like a PC serial port:
    TXD on pin 3, ground on pin 5 (the SCT-50 manual says a standard straight-through male-to-female
    DB9 cable works, as for a PC).  If nothing shows up, try swapping TX and RX.
    On the SCT-50 (SYSTEM SETUP menu): ONLINE = Y, BAUD = 9600 (must match TARGET_BAUD), and
    ADDRESS = 00 or the same number as SCT_ADDRESS below.  Its LED flickers when serial data arrives.
"""
import sys
import time

# =========================== CONFIGURATION ===========================
EAS_BAUD = 9600                 # COM2 speed, fixed by the manual
EAS_UART_ID = 0                 # UART0 -> GP0 (TX) / GP1 (RX)
EAS_TX_PIN = 0
EAS_RX_PIN = 1

ENABLE_TARGET_OUTPUT = True    # True once the Horita SCT-50 is actually connected to UART1
SCT_DRY_RUN = False              # while output is disabled: still build the SCT-50 commands and LOG them
TARGET_UART_ID = 1              # UART1 -> GP4 (TX) / GP5 (RX)
TARGET_TX_PIN = 4
TARGET_RX_PIN = 5
TARGET_BAUD = 9600              # SCT-50 offers 4800 / 9600 / 38.4K; set the same in its SYSTEM SETUP

# --- Horita SCT-50 display settings ---
SCT_ADDRESS = 0                 # 0 = broadcast (reaches any SCT-50); or 1-99 to target one unit
SCT_INIT_ON_START = True        # send display/size/position setup at startup (NOT saved in the SCT-50)
SCT_H_SIZE = 1                  # character width  1-4   (manual command 45)
SCT_V_SIZE = 2                  # character height 1-4   (5/6 = split-screen modes)
SCT_H_POS = 17                  # horizontal position 01-63 (command 44)
SCT_V_POS = 24                   # vertical position   01-63 (command 46)
SHOW_EVENT_TITLE = True         # put the event name (e.g. TORNADO WARNING) at the top of each page
SCT_PAGE_S = 8                  # seconds each 9-line page stays up when the alert needs several pages
SCT_DISPLAY_S = 300             # clear the screen this long after the alert arrives (0 = never clear)
SCT_MAX_PAGES = 12              # safety limit on how long a message can run
SCT_CMD_GAP_MS = 15             # pause after each command (the manual asks for 7 ms or more on some)
SCT_SPACE_BYTE = 0x09           # the SCT-50's "clear/transparent" blank. If blanks show up as boxes
                                # or odd symbols on screen, try 0x20 instead.

COMPLETE_HANDSHAKE = True       # also request audio + EOM so the 911 ends the sequence normally
LOG_LEVEL = "DEBUG"             # DEBUG (everything) / INFO / WARN / ERROR
LOG_RAW_BYTES = True            # hex-dump every chunk read from and written to the 911
LOG_SCT_BYTES = False           # hex-dump every command sent to the SCT-50 (very noisy; the page text
                                # is still logged at INFO level either way)
HEARTBEAT_S = 30                # print a status line this often while idle
T_SHORT_MS = 30000              # give up if the 911 goes quiet this long mid-sequence
T_VOICE_MS = 15 * 60 * 1000     # in manual mode the 911 waits for the operator to press SEND EOM

# =========================== PROTOCOL CONSTANTS ===========================
STX, ETX = 0x02, 0x03
C_AUDIO, C_VOICE, C_XLAT, C_READY, C_TEXT, C_ANNC, C_VONLY, C_EXC = (
    0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B)
CTL_NAMES = {
    C_AUDIO: "AUDIO_HDR", C_VOICE: "VOICE_EOM", C_XLAT: "TRANSLATION",
    C_READY: "MSG_READY", C_TEXT: "LAST_TEXT", C_ANNC: "USER_ANNOUNCE",
    C_VONLY: "VOICE_ONLY", C_EXC: "EXCEPTION",
}

# session states
IDLE, WAIT_XLAT, WAIT_AUDIO_ACK, WAIT_VOICE_ACK = range(4)
STATE_NAMES = {IDLE: "IDLE", WAIT_XLAT: "WAIT_TRANSLATION",
               WAIT_AUDIO_ACK: "WAIT_AUDIO_ACK", WAIT_VOICE_ACK: "WAIT_VOICE_EOM_ACK"}

# =========================== LOOKUP TABLES (for readable logs) ===========================
# Originators (who issued the alert)
ORG_NAMES = {"EAS": "EAS participant", "CIV": "Civil authorities",
             "WXR": "National Weather Service", "PEP": "Primary Entry Point / US government"}

# Current FCC event list (47 CFR 11.31).  Your 911's own firmware only knows ~32 of
# these, but the raw header always carries the code, so we can name any of them here.
EVENT_NAMES = {
    "EAN": "Emergency Action Notification", "EAT": "Emergency Action Termination (obsolete)",
    "NIC": "National Information Center", "NPT": "National Periodic Test",
    "RMT": "Required Monthly Test", "RWT": "Required Weekly Test",
    "ADR": "Administrative Message", "AVA": "Avalanche Watch", "AVW": "Avalanche Warning",
    "BLU": "Blue Alert", "BZW": "Blizzard Warning", "CAE": "Child Abduction Emergency",
    "CDW": "Civil Danger Warning", "CEM": "Civil Emergency Message",
    "CFA": "Coastal Flood Watch", "CFW": "Coastal Flood Warning", "DMO": "Practice/Demo Warning",
    "DSW": "Dust Storm Warning", "EQW": "Earthquake Warning", "EVI": "Evacuation Immediate",
    "EWW": "Extreme Wind Warning", "FFA": "Flash Flood Watch", "FFS": "Flash Flood Statement",
    "FFW": "Flash Flood Warning", "FLA": "Flood Watch", "FLS": "Flood Statement",
    "FLW": "Flood Warning", "FRW": "Fire Warning", "HLS": "Hurricane Statement",
    "HMW": "Hazardous Materials Warning", "HUA": "Hurricane Watch", "HUW": "Hurricane Warning",
    "HWA": "High Wind Watch", "HWW": "High Wind Warning", "LAE": "Local Area Emergency",
    "LEW": "Law Enforcement Warning", "MEP": "Missing and Endangered Persons",
    "NMN": "Network Message Notification", "NUW": "Nuclear Power Plant Warning",
    "RHW": "Radiological Hazard Warning", "SMW": "Special Marine Warning",
    "SPS": "Special Weather Statement", "SPW": "Shelter in Place Warning",
    "SSA": "Storm Surge Watch", "SSW": "Storm Surge Warning", "SVA": "Severe Thunderstorm Watch",
    "SVR": "Severe Thunderstorm Warning", "SVS": "Severe Weather Statement",
    "TOA": "Tornado Watch", "TOE": "911 Telephone Outage Emergency", "TOR": "Tornado Warning",
    "TRA": "Tropical Storm Watch", "TRW": "Tropical Storm Warning", "TSA": "Tsunami Watch",
    "TSW": "Tsunami Warning", "VOW": "Volcano Warning", "WSA": "Winter Storm Watch",
    "WSW": "Winter Storm Warning",
}


# =========================== LOGGING ===========================
_LEVELS = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}


def _now():
    """Milliseconds since boot (MicroPython) or a monotonic clock (desktop testing).
    Note: MicroPython's ticks_ms() wraps after ~12 days, so long-running timestamps repeat."""
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.monotonic() * 1000)


def _elapsed(since):
    """Milliseconds elapsed since a value previously returned by _now()."""
    try:
        return time.ticks_diff(time.ticks_ms(), since)
    except AttributeError:
        return _now() - since


def log(level, msg):
    """Print one timestamped log line.  Timestamp = seconds since the Pico booted."""
    if _LEVELS[level] >= _LEVELS[LOG_LEVEL]:
        print("[%9.3f] %-5s %s" % (_now() / 1000.0, level, msg))


def hexdump(data):
    """Return 'HH HH HH | printable-ascii' so raw serial traffic is easy to read."""
    data = bytes(data)
    hx = " ".join("%02X" % b for b in data)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return "%s | %s" % (hx, asc)


# =========================== EAS HEADER PARSING ===========================
def parse_header(raw):
    """Best-effort decode of a SAME header such as
         ZCZC-WXR-TOR-042101-042091+0030-3011500-KPHI/NWS-
       Returns a dict; 'problems' lists anything that didn't look right.  The 911 might
       not send the header in exactly this form, so failure here is logged, never fatal."""
    info = {"raw": "", "problems": []}
    try:
        s = bytes(raw).decode("ascii", "replace").strip()
        info["raw"] = s
        body = s[4:] if s.startswith("ZCZC") else s
        if not s.startswith("ZCZC"):
            info["problems"].append("does not start with ZCZC")
        body = body.strip("-")
        left, plus, right = body.partition("+")
        if not plus:
            info["problems"].append("no '+' separator before the duration")
        parts = left.split("-")
        info["org"] = parts[0] if len(parts) > 0 else ""
        info["event"] = parts[1] if len(parts) > 1 else ""
        info["locations"] = [p for p in parts[2:] if p]
        rparts = right.split("-")
        info["duration"] = rparts[0] if len(rparts) > 0 else ""      # hhmm
        info["issued"] = rparts[1] if len(rparts) > 1 else ""        # JJJHHMM, UTC
        info["sender"] = rparts[2] if len(rparts) > 2 else ""        # 8-char station ID
        if len(info["org"]) != 3:
            info["problems"].append("originator code is not 3 characters")
        if len(info["event"]) != 3:
            info["problems"].append("event code is not 3 characters")
        for loc in info["locations"]:
            if len(loc) != 6 or not loc.isdigit():
                info["problems"].append("odd location code %r" % loc)
        if len(info["duration"]) != 4 or not info["duration"].isdigit():
            info["problems"].append("odd duration %r" % info["duration"])
        if len(info["issued"]) != 7 or not info["issued"].isdigit():
            info["problems"].append("odd issue time %r" % info["issued"])
    except Exception as e:                                           # never let parsing crash us
        info["problems"].append("parser error: %r" % e)
    return info


def describe_location(code):
    """Human label for a 6-digit PSSCCC location code."""
    if code == "000000":
        return "000000 (ALL U.S.)"
    if len(code) == 6 and code.endswith("000"):
        return "%s (entire state %s)" % (code, code[1:3])
    return code


def describe_header(info):
    """One-line summary of a parsed header for the log."""
    ev = info.get("event", "?")
    org = info.get("org", "?")
    dur = info.get("duration", "")
    dur_txt = ("%sh%sm" % (dur[:2], dur[2:])) if len(dur) == 4 else dur
    issued = info.get("issued", "")
    iss_txt = ("day %s %s:%s UTC" % (issued[:3], issued[3:5], issued[5:7])) if len(issued) == 7 else issued
    return "%s = %s | from %s = %s | areas: %s | valid %s | issued %s | sender %s" % (
        ev, EVENT_NAMES.get(ev, "UNKNOWN EVENT CODE"),
        org, ORG_NAMES.get(org, "unknown originator"),
        ", ".join(describe_location(l) for l in info.get("locations", [])) or "none",
        dur_txt, iss_txt, info.get("sender", ""))


# =========================== PROTOCOL ENGINE ===========================
def frame(ctl, data=b""):
    """Build a complete frame: STX + control byte + data + ETX."""
    return bytes([STX, ctl]) + data + bytes([ETX])


class CGEndpoint:
    """The 'character generator' side of the EAS 911 COM2 protocol.

    send(bytes)        - writes bytes to the 911 (UART write).
    on_text(text, hdr) - called with the decoded alert text and the raw header bytes.
    feed(bytes)        - give it everything read from the UART, in any size chunks.
    tick()             - call regularly so a stalled session times out.
    """

    def __init__(self, send, on_text):
        self._send = send
        self.on_text = on_text
        self.buf = bytearray()      # bytes of the frame currently being received
        self.in_frame = False
        self.state = IDLE
        self.t_state = _now()       # when the state last changed
        self.t_session = _now()     # when the current message began
        self.header = b""
        # running counters, printed by the heartbeat
        self.stats = {"bytes": 0, "frames": 0, "messages": 0, "completed": 0,
                      "aborted": 0, "timeouts": 0, "stray_bytes": 0, "unexpected": 0}

    # ---- sending ----
    def send(self, ctl, data=b""):
        out = frame(ctl, data)
        log("INFO", "TX -> 911: %s" % CTL_NAMES.get(ctl, "0x%02X" % ctl))
        if LOG_RAW_BYTES:
            log("DEBUG", "TX raw: " + hexdump(out))
        self._send(out)

    # ---- state handling ----
    def _set(self, new_state, why=""):
        if new_state != self.state:
            log("DEBUG", "state %s -> %s %s" % (STATE_NAMES[self.state], STATE_NAMES[new_state], why))
        self.state = new_state
        self.t_state = _now()

    def tick(self):
        """Abandon a session if the 911 stops responding (so we never get stuck)."""
        if self.state == IDLE:
            return
        limit = T_VOICE_MS if self.state == WAIT_VOICE_ACK else T_SHORT_MS
        waited = _elapsed(self.t_state)
        if waited > limit:
            self.stats["timeouts"] += 1
            log("WARN", "TIMEOUT: no reply for %.1f s in state %s; abandoning this message"
                % (waited / 1000.0, STATE_NAMES[self.state]))
            self._set(IDLE, "(timeout)")

    # ---- byte stream -> frames ----
    def feed(self, data):
        """Split the incoming byte stream into frames at STX ... ETX boundaries."""
        self.stats["bytes"] += len(data)
        stray = bytearray()
        for b in data:
            if b == STX:                               # a new frame starts (discard any partial one)
                if self.in_frame and self.buf:
                    log("WARN", "new STX while a frame was incomplete; dropped: " + hexdump(self.buf))
                self.buf = bytearray()
                self.in_frame = True
            elif b == ETX and self.in_frame:           # frame complete
                self.in_frame = False
                if self.buf:
                    self.stats["frames"] += 1
                    self._frame(self.buf[0], bytes(self.buf[1:]))
                else:
                    log("WARN", "empty frame (STX ETX with no control byte)")
                self.buf = bytearray()
            elif self.in_frame:
                self.buf.append(b)
                if len(self.buf) > 600:                # runaway guard: ETX never arrived
                    log("ERROR", "frame longer than 600 bytes with no ETX; discarding")
                    self.in_frame = False
                    self.buf = bytearray()
            else:
                stray.append(b)                        # byte outside any frame (noise / wrong baud?)
        if stray:
            self.stats["stray_bytes"] += len(stray)
            log("WARN", "%d byte(s) outside any frame (noise or wrong baud rate?): %s"
                % (len(stray), hexdump(stray)))

    # ---- protocol logic ----
    def _frame(self, ctl, payload):
        name = CTL_NAMES.get(ctl, "UNKNOWN(0x%02X)" % ctl)
        log("INFO", "RX <- 911: %s%s" % (name, (" (%d data bytes)" % len(payload)) if payload else " (no data)"))
        if LOG_RAW_BYTES:
            log("DEBUG", "RX frame: " + hexdump(frame(ctl, payload)))

        if ctl == C_READY:                             # 911 announces a new alert
            if self.state != IDLE:
                log("INFO", "duplicate MSG_READY ignored (already handling a message)")
                return
            self.stats["messages"] += 1
            self.t_session = _now()
            self.header = payload
            info = parse_header(payload)
            log("INFO", "ALERT HEADER: " + info["raw"])
            log("INFO", "  decoded: " + describe_header(info))
            for p in info["problems"]:
                log("WARN", "  header note: " + p)
            self._set(WAIT_XLAT, "(requesting translation)")
            self.send(C_XLAT)                          # answer fast: the 911 retries 3x then aborts

        elif ctl == C_XLAT and payload and self.state == WAIT_XLAT:
            try:
                text = payload.decode("ascii")
            except Exception:
                text = repr(payload)
                log("WARN", "translation was not clean ASCII")
            log("INFO", "TRANSLATION (%.2f s after notice): %s" % (_elapsed(self.t_session) / 1000.0, text))
            try:
                self.on_text(text, self.header)        # user callback: a bug there must not kill us
            except Exception as e:
                log("ERROR", "on_text handler failed: %r" % e)
            if COMPLETE_HANDSHAKE:
                self._set(WAIT_AUDIO_ACK, "(requesting audio header)")
                self.send(C_AUDIO)
            else:
                log("INFO", "handshake completion disabled; message handled")
                self.stats["completed"] += 1
                self._set(IDLE)

        elif ctl == C_AUDIO and not payload and self.state == WAIT_AUDIO_ACK:
            self._set(WAIT_VOICE_ACK, "(requesting voice + EOM)")
            self.send(C_VOICE)

        elif ctl == C_VOICE and not payload and self.state == WAIT_VOICE_ACK:
            self.stats["completed"] += 1
            log("INFO", "SEQUENCE COMPLETE in %.1f s" % (_elapsed(self.t_session) / 1000.0))
            self._set(IDLE)

        elif ctl == C_EXC:                             # 911 aborted (cancelled, timed out, ...)
            self.stats["aborted"] += 1
            log("WARN", "911 reported EXCEPTION/abort; session reset (payload %r)" % (payload,))
            self._set(IDLE)

        else:                                          # valid frame, but not what we expected now
            self.stats["unexpected"] += 1
            log("WARN", "unexpected frame %s in state %s; ignored"
                % (name, STATE_NAMES[self.state]))


# =========================== OUTPUT SIDE: HORITA SCT-50 ===========================
# The SCT-50 is a serial-controlled video titler: a 9-line x 20-character text screen.
# Serial protocol (SCT-50 manual, chapter 5): every command is
#       ESC (0x1B) + 2-digit ASCII address + 2-digit ASCII command + optional data
# Commands used here (numbers are the manual's decimal command codes):
#   07 display ON     09 background ON    11 white characters   14 line numbers OFF
#   20 enable write to screen             22 enable write to memory page
#   25 clear all lines (allow 100 ms)     26 ddd set character pointer 001-180
#   27 data... write characters from the pointer (continues until the next ESC)
#   35 time display OFF   40 date display OFF
#   44 dd H position   45 d H size   46 dd V position   47 d V size
ESC = 0x1B
SCT_COLS, SCT_ROWS = 20, 9
# Characters the SCT-50 can show (its Table 4-3): upper-case A-Z, 0-9 and  . , ' & : ? ! ~ ( ) / * - + =
SCT_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,'&:?!~()/*-+=")
# Stand-ins for common characters it cannot display
SCT_SUBS = {'"': "'", ";": ",", "_": "-", "[": "(", "]": ")", "{": "(", "}": ")", "<": "-",
            ">": "-", "%": " PCT ", "#": " NO ", "@": " AT ", "$": " DOLLARS ", "\\": "/", "|": "/"}


def _sleep_ms(ms):
    try:
        time.sleep_ms(ms)
    except AttributeError:                    # desktop testing
        time.sleep(ms / 1000.0)


def sct_clean(text):
    """Upper-case the text, swap unsupported characters, and collapse runs of whitespace."""
    out = []
    for ch in text.upper():
        if ch in SCT_ALLOWED or ch == " ":
            out.append(ch)
        elif ch in SCT_SUBS:
            out.append(SCT_SUBS[ch])
        else:
            out.append(" ")                   # anything else (newlines, accents, ...) becomes a space
    return " ".join("".join(out).split())


def _join_times(words):
    """Glue a clock time to its AM/PM so a line never ends with '4:50' and starts with 'PM.'
    e.g. ['UNTIL', '4:50', 'PM.'] -> ['UNTIL', '4:50 PM.']"""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if nxt.rstrip(".,") in ("AM", "PM") and any(c.isdigit() for c in w):
            out.append(w + " " + nxt)
            i += 2
        else:
            out.append(w)
            i += 1
    return out


def sct_wrap(text, width=SCT_COLS):
    """Convert text to SCT-50 lines of at most 20 characters.
    The 911 already splits its translation into sensible lines (newlines), so each newline
    starts a new line here; only lines longer than 20 characters are word-wrapped."""
    lines = []
    for para in text.split("\n"):
        words = _join_times([w for w in sct_clean(para).split(" ") if w])
        cur = ""
        for word in words:
            while len(word) > width:          # break a too-long word across lines
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:width])
                word = word[width:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= width:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


class SCT50:
    """Drives a Horita SCT-50.  show_alert() paginates an alert onto the 9x20 screen;
    service() must be called often so pages rotate and the screen clears on time."""

    def __init__(self, write, dry_run=False):
        self._write = write                   # function that sends bytes (UART.write), or None
        self.dry_run = dry_run                # True: build + log commands but never transmit
        self.pages = []                       # each page = list of up to 9 text lines
        self.page_idx = 0
        self.t_page = _now()                  # when the current page went up
        self.t_show = _now()                  # when the alert first went up
        self.showing = False

    # ---- low level ----
    def _out(self, pkt, label):
        if LOG_SCT_BYTES:
            log("DEBUG", "SCT-50 %s%s [%s]: %s" % ("(dry run) " if self.dry_run else "",
                                                   "TX", label, hexdump(pkt)))
        if not self.dry_run and self._write:
            self._write(pkt)

    def _cmd(self, cmd, data=b"", wait_ms=None):
        """Send ESC + address + command (+ data), then pause so the SCT-50 can finish."""
        pkt = bytes([ESC]) + ("%02d%02d" % (SCT_ADDRESS, cmd)).encode() + data
        self._out(pkt, "cmd %02d" % cmd)
        _sleep_ms(SCT_CMD_GAP_MS if wait_ms is None else wait_ms)

    # ---- high level ----
    def init_display(self):
        """One-time setup so the screen looks as expected (not stored in the SCT-50 itself)."""
        log("INFO", "SCT-50: initialising display (addr %02d, size %dx%d, pos %d,%d)"
            % (SCT_ADDRESS, SCT_H_SIZE, SCT_V_SIZE, SCT_H_POS, SCT_V_POS))
        self._cmd(7)                          # video display on
        self._cmd(9)                          # background on (readable over any picture)
        self._cmd(11)                         # white characters
        self._cmd(14)                         # no line numbers
        self._cmd(35)                         # hide the clock
        self._cmd(40)                         # hide the date
        self._cmd(45, str(SCT_H_SIZE).encode())
        self._cmd(47, str(SCT_V_SIZE).encode())
        self._cmd(44, ("%02d" % SCT_H_POS).encode())
        self._cmd(46, ("%02d" % SCT_V_POS).encode())
        self._cmd(20)                         # enable writing to the screen
        self._cmd(22)                         # enable writing to the memory page
        self._cmd(25, wait_ms=120)            # clear all lines (manual: allow 100 ms)

    def _draw(self, idx):
        """Write one page: exactly 180 characters, so no leftover text from earlier pages."""
        lines = self.pages[idx]
        screen = bytearray()
        for r in range(SCT_ROWS):
            line = lines[r][:SCT_COLS] if r < len(lines) else ""
            for ch in line:
                screen.append(SCT_SPACE_BYTE if ch == " " else ord(ch))
            screen.extend([SCT_SPACE_BYTE] * (SCT_COLS - len(line)))   # pad the line to 20
        log("INFO", "SCT-50: page %d/%d: %s" % (idx + 1, len(self.pages), " / ".join(lines)))
        self._cmd(26, b"001")                 # character pointer to the top-left corner
        self._cmd(27, bytes(screen), wait_ms=0)   # write all 180 characters

    def show_alert(self, title, text):
        """Display an alert: optional title lines, then the text split into 20-column pages."""
        title_lines = sct_wrap(title)[:2] if (SHOW_EVENT_TITLE and title) else []
        body = sct_wrap(text)
        cap = SCT_ROWS - len(title_lines)     # text lines that fit under the title
        chunks = [body[i:i + cap] for i in range(0, len(body), cap)] or [[]]
        if len(chunks) > SCT_MAX_PAGES:
            log("WARN", "SCT-50: message needs %d pages; truncating to %d" % (len(chunks), SCT_MAX_PAGES))
            chunks = chunks[:SCT_MAX_PAGES]
        self.pages = [title_lines + c for c in chunks]
        self.page_idx = 0
        log("INFO", "SCT-50: showing alert in %d page(s)" % len(self.pages))
        self._draw(0)
        self.t_page = self.t_show = _now()
        self.showing = True

    def clear(self):
        log("INFO", "SCT-50: clearing screen")
        self._cmd(25, wait_ms=120)
        self.showing = False

    def service(self):
        """Call every loop: rotates multi-page alerts and clears the screen when time is up."""
        if not self.showing:
            return
        if SCT_DISPLAY_S and _elapsed(self.t_show) > SCT_DISPLAY_S * 1000:
            self.clear()
        elif len(self.pages) > 1 and _elapsed(self.t_page) >= SCT_PAGE_S * 1000:
            self.page_idx = (self.page_idx + 1) % len(self.pages)
            self._draw(self.page_idx)
            self.t_page = _now()


def deliver(text, header, target=None):
    """Called once per decoded alert.  Always logs; also drives the SCT-50 if one is configured."""
    log("INFO", "DELIVER: %s" % text)
    if target is None:
        log("DEBUG", "no output target configured; nothing sent")
        return
    info = parse_header(header)               # use our own event name: works even for codes the 911 lacks
    name = EVENT_NAMES.get(info.get("event", ""), "")
    target.show_alert(name, text)


# =========================== MAIN LOOP ===========================
def _make_led():
    """Optional heartbeat LED; different Pico variants name it differently."""
    from machine import Pin
    for name in ("LED", 25):
        try:
            return Pin(name, Pin.OUT)
        except Exception:
            pass
    return None


def main():
    from machine import UART, Pin
    log("INFO", "=== EAS 911 character-generator adapter starting ===")
    log("INFO", "python %s | log level %s | complete handshake: %s | target output: %s"
        % (sys.version.split(";")[0], LOG_LEVEL, COMPLETE_HANDSHAKE, ENABLE_TARGET_OUTPUT))

    eas = UART(EAS_UART_ID, baudrate=EAS_BAUD, bits=8, parity=None, stop=1,
               tx=Pin(EAS_TX_PIN), rx=Pin(EAS_RX_PIN), rxbuf=1024, timeout=0)
    log("INFO", "listening to 911 on UART%d at %d 8-N-1 (TX=GP%d RX=GP%d)"
        % (EAS_UART_ID, EAS_BAUD, EAS_TX_PIN, EAS_RX_PIN))

    target = None
    if ENABLE_TARGET_OUTPUT:
        tuart = UART(TARGET_UART_ID, baudrate=TARGET_BAUD, bits=8, parity=None, stop=1,
                     tx=Pin(TARGET_TX_PIN), rx=Pin(TARGET_RX_PIN), timeout=0)
        target = SCT50(tuart.write)
        log("INFO", "SCT-50 output on UART%d at %d baud (TX=GP%d)" % (TARGET_UART_ID, TARGET_BAUD, TARGET_TX_PIN))
    elif SCT_DRY_RUN:
        target = SCT50(None, dry_run=True)
        log("INFO", "SCT-50 DRY RUN: commands are built and logged but NOT transmitted")
    if target and SCT_INIT_ON_START:
        target.init_display()

    def write_to_911(data):
        eas.write(data)

    ep = CGEndpoint(send=write_to_911, on_text=lambda t, h: deliver(t, h, target))
    led = _make_led()
    last_beat = _now()
    warned_silent = False
    log("INFO", "ready; waiting for the 911 (send a test message in a non-Practice mode)")

    while True:
        try:
            data = eas.read()                          # returns None when nothing is waiting
            if data:
                if LOG_RAW_BYTES:
                    log("DEBUG", "RX raw (%d bytes): %s" % (len(data), hexdump(data)))
                ep.feed(data)
            ep.tick()
            if target:
                target.service()                       # page rotation / auto-clear

            # Periodic status line so you can see the script is alive.
            if _elapsed(last_beat) >= HEARTBEAT_S * 1000:
                last_beat = _now()
                s = ep.stats
                log("INFO", "heartbeat | state %s | bytes %d | frames %d | messages %d | "
                    "completed %d | aborted %d | timeouts %d | stray %d | unexpected %d"
                    % (STATE_NAMES[ep.state], s["bytes"], s["frames"], s["messages"],
                       s["completed"], s["aborted"], s["timeouts"], s["stray_bytes"], s["unexpected"]))
                if led:
                    led.toggle()
                if s["bytes"] == 0 and not warned_silent:
                    warned_silent = True
                    log("WARN", "no bytes received from the 911 yet. Check: MAX3232 wiring, TX/RX "
                        "swapped, 911 menu item 18 enabled, COM expander installed, not in PRACTICE mode.")
            time.sleep_ms(5)
        except KeyboardInterrupt:
            log("INFO", "stopped by user")
            raise
        except Exception as e:                         # log and keep running
            log("ERROR", "main loop error: %r" % e)
            try:
                sys.print_exception(e)
            except Exception:
                pass
            time.sleep_ms(500)


if __name__ == "__main__":
    main()
