# EAS 911 Character Generator Adapter
 
This document has the contents written in ASD-STE100 style English for clarity and direct instruction.
 
---
 
## Contents
 
1. [Description](#description)
2. [Test status](#test-status)
3. [Equipment](#equipment)
4. [Wiring](#wiring)
5. [EAS 911 setup](#eas-911-setup)
6. [Install the software on the Pico board](#install-the-software-on-the-pico-board)
7. [Configuration](#configuration)
8. [Operation and log](#operation-and-log)
9. [Tests without the EAS 911](#tests-without-the-eas-911)
10. [Output drivers](#output-drivers)
11. [Add support for another CG](#add-support-for-another-cg)
12. [Protocol references](#protocol-references)
13. [Troubleshooting](#troubleshooting)
14. [Known limits](#known-limits)
15. [Future work](#future-work)
---
 
## Description
 
The adapter is a MicroPython program. It operates on a Raspberry Pi Pico board that has an RP2040 chip.
 
The adapter connects between a TFT EAS 911 and one or more video character generators (CGs). It operates as the CG on port COM2 of the EAS 911. It receives each decoded alert. It changes the alert text for the CG that you connect.
 
The goal is one input and many outputs. The input side has one program for the TFT CG protocol. Each CG has its own output driver. At this time, one output driver is available. It is for the Horita SCT-50.
 
**CAUTION:** This project is not FCC-certified EAS equipment. Do not connect the audio output or the relay contacts of the EAS 911 to a transmitter or to a cable system. Connect them only if you are authorized and you intend to do so. During tests, use Practice mode and keep the outputs disconnected.
 
### Data flow
 
```
 EAS 911  --RS-232-->  Pico board (this software)  --RS-232-->  Character generator(s)
 COM2                  Input side:                              One output driver
                       - frame parser                           for each CG
                       - handshake state machine
                       - SAME header decoder
                       - event and originator tables
                       - log
```
 
### Steps for each alert
 
1. The EAS 911 receives an alert.
2. The EAS 911 sends a "message ready" frame on COM2. The frame contains the raw SAME header. An example is `ZCZC-EAS-NUW-042045+0015-3071135-INTERMOD-`.
3. The adapter immediately requests the plain-English translation from the EAS 911.
4. The adapter decodes the header. It finds the originator, event, areas, duration, issue time and sender. It writes them to the log.
5. The adapter sends the translated text, the event name and the raw header to the output driver.
6. The adapter can also complete the audio and EOM handshake. Then the EAS 911 ends the sequence correctly.
The adapter reads the raw header. Therefore it can show the name of any current FCC event code. This is also true for codes that the firmware of the EAS 911 does not know.
 
---
 
## Test status
 
| Area | Status |
|---|---|
| EAS 911 COM2 handshake (message ready, translation, audio, voice and EOM) | Tested from end to end with a log from a real EAS 911 |
| Header decoder and event names | Tested with a real header (`NUW`, Delaware County PA) |
| Translation that arrives in several parts | Tested (five parts in about 0.3 seconds) |
| Horita SCT-50 output | The display works after the wiring was corrected. The first tests were manual tests from the Pico shell |
| Other character generators | Not available |
 
Test equipment:
 
- A Pico-class board with an RP2040 chip (marked RP2-B2). It had MicroPython v1.29.0.
- A TFT EAS 911. The chip labels seem to read V.87.2 EN.
- A Horita SCT-50.
---
 
## Equipment
 
- A Raspberry Pi Pico board, or an RP2040 clone. Pins GP0, GP1, GP4 and GP5 must be available.
- Two MAX3232 modules (or SP3232 modules) that operate at 3.3 V. Use one module for the EAS 911 and one module for the SCT-50.
- DB9 cables. Use straight-through cables or null-modem cables (see [Troubleshooting](#troubleshooting)).
- A USB data cable. Some USB cables only supply power.
- A 4-Port Communications Expander in the EAS 911. COM2 (J302) is on this option.
- For the SCT-50: a composite video source and a monitor. The SCT-50 shows no text without a video signal.
**CAUTION:** Do not connect the RS-232 lines directly to the Pico board. The RS-232 voltage is too high for the Pico board. This can cause damage to the board. Always use a MAX3232 module.
 
---
 
## Wiring
 
The drawing shows the standard Pico pin layout. The USB connector is at the top. If you use a clone, use the GP numbers that are printed on the board. Do not use the position of the pins.
 
```
                    +-----[ USB ]-----+
  MOD 1  TXD  <-----| 1 GP0       VBUS 40|
  MOD 1  RXD  ----->| 2 GP1       VSYS 39|
  MOD 1  GND  ------| 3 GND        GND 38|
                    | 4 GP2     3V3_EN 37|
                    | 5 GP3    3V3 OUT 36|------+----> MOD 1  VCC
  MOD 2  TXD  <-----| 6 GP4   ADC_VREF 35|      +----> MOD 2  VCC
  MOD 2  RXD  ----->| 7 GP5       GP28 34|
  MOD 2  GND  ------| 8 GND        GND 33|
                    | 9 GP6       GP27 32|
                    |10 GP7       GP26 31|
                    |11 GP8        RUN 30|
                    |12 GP9       GP22 29|
                    |13 GND        GND 28|
                    |14 GP10      GP21 27|
                    |15 GP11      GP20 26|
                    |16 GP12      GP19 25|
                    |17 GP13      GP18 24|
                    |18 GND        GND 23|
                    |19 GP14      GP17 22|
                    |20 GP15      GP16 21|
                    +-----------------+
 
  MOD 1 DB9 side  ===== DB9 cable =====>  EAS 911  COM2 (J302)
  MOD 2 DB9 side  ===== DB9 cable =====>  HORITA SCT-50  SERIAL IN
```
 
### Connection list
 
| Pico pin | Name | Connect to |
|---|---|---|
| 1 | GP0 (UART0 TX) | Module 1 TXD |
| 2 | GP1 (UART0 RX) | Module 1 RXD |
| 3 | GND | Module 1 GND |
| 6 | GP4 (UART1 TX) | Module 2 TXD |
| 7 | GP5 (UART1 RX) | Module 2 RXD (optional; the SCT-50 driver only sends data) |
| 8 | GND | Module 2 GND |
| 36 | 3V3 OUT | VCC of module 1 and VCC of module 2 |
 
### Wiring notes
 
- Supply power to the Pico board through USB. Use a PC or a USB charger. Do not supply power from the EAS 911.
- Connect all grounds together.
- **EAS 911 side:** In the EAS 911 manual, COM2 uses pin 2 as Rx, pin 3 as Tx and pin 5 as GND. Use a straight-through cable first. If the log shows no bytes, use a null-modem cable or swap TX and RX.
- **SCT-50 side:** The SCT-50 receives data on pin 3. Many MAX3232 modules send data on pin 2. In this case, use a null-modem adapter. The LED on the SCT-50 flashes when it receives a character. Use the LED to check the data path.
- Some modules have TXD and RXD labels that show the RS-232 side. If data does not flow, swap the two GP wires on the module pins.
---
 
## EAS 911 setup
 
Log in to the setup menu:
 
1. Push **PASSWORD**.
2. Enter the primary password.
3. Push **PASSWORD** again.
4. Enter the setup password.
The factory default passwords are in the EAS 911 manual. Change them.
 
Set these items:
 
| Menu item | Setting |
|---|---|
| 18, Enable Char Gen Interface | Select **STD** (TFT Standard interface). CODI is a different protocol for Chyron units. The options VD1, ALT1 and ALT2 are not in the manual that this project uses. |
| 2 and 3, Time zone and DST | Set the UTC offset. Decide how to do the DST setting. The DST rules in the manual are older than the 2007 US change. |
 
Make sure of these conditions:
 
- Practice mode is off during the CG link test. The EAS 911 does not send data to the CG in Practice mode.
- The adapter is on and operates when the EAS 911 is in Auto mode. If STD is selected and the CG does not respond, the EAS 911 stops (aborts) the auto-forwarded message.
- The times in the translation come from the clock of the EAS 911. They do not come from the adapter.
---
 
## Install the software on the Pico board
 
### Install MicroPython
 
1. Install Thonny (thonny.org) on your PC.
2. Put the Pico board in BOOTSEL mode. Hold the BOOTSEL button and connect the USB cable. Then release the button.
3. In Thonny, select **Tools**, then **Options**, then **Interpreter**.
4. Select **Install or update MicroPython**. Set the family to **rp2**. Set the variant to **Raspberry Pi Pico / Pico H**.
5. As an alternative, download the `.uf2` file from micropython.org/download/RPI_PICO/. Then put the file on the **RPI-RP2** drive.
NOTE: After MicroPython is installed, the board does not show as a drive. This is normal. Thonny uses a serial (COM) port.
 
### Install the adapter
 
1. In Thonny, select the interpreter **MicroPython (Raspberry Pi Pico)**. A `>>>` prompt must show in the Shell.
2. Select **View**, then **Files**.
3. In the **This computer** section, find `eas911_cg_adapter.py`.
4. Right-click the file. Select **Upload to /**.
5. In the **Raspberry Pi Pico** section, right-click the file. Select **Rename**.
6. Enter the name **`main.py`**.
The Pico board runs `main.py` automatically each time that it starts.
 
### Start and stop the adapter
 
1. Open `main.py` in Thonny.
2. Push the green **Run** button. The log shows in the Shell.
3. To stop the adapter, push the red **Stop** button or push Ctrl+C.
4. If the adapter already operates when you connect, push **Stop** one or two times. Then the `>>>` prompt shows.
---
 
## Configuration
 
All settings are constants at the top of the file. To change a setting, edit the file and upload it again.
 
| Setting | Default | Meaning |
|---|---|---|
| `EAS_BAUD` | 9600 | Speed of COM2. The EAS 911 protocol sets this value |
| `EAS_UART_ID`, `EAS_TX_PIN`, `EAS_RX_PIN` | 0, 0, 1 | UART for the EAS 911 |
| `ENABLE_TARGET_OUTPUT` | `False` | Set to `True` when the output CG is connected to UART1 |
| `SCT_DRY_RUN` | `True` | If output is disabled, the adapter makes the SCT-50 commands and writes them to the log |
| `TARGET_UART_ID`, `TARGET_TX_PIN`, `TARGET_RX_PIN`, `TARGET_BAUD` | 1, 4, 5, 9600 | UART for the output CG |
| `COMPLETE_HANDSHAKE` | `True` | Request the audio header and the voice and EOM, so that the EAS 911 ends the sequence correctly (see [Known limits](#known-limits)) |
| `LOG_LEVEL` | `"DEBUG"` | Log detail: `DEBUG`, `INFO`, `WARN` or `ERROR` |
| `LOG_RAW_BYTES` | `True` | Write the data to and from the EAS 911 in hexadecimal |
| `LOG_SCT_BYTES` | `False` | Write each SCT-50 command in hexadecimal (very large log) |
| `HEARTBEAT_S` | 30 | Seconds between status lines |
| `T_SHORT_MS`, `T_VOICE_MS` | 30 seconds, 15 minutes | Time limits for an EAS 911 session that stops |
 
### SCT-50 settings
 
| Setting | Default | Meaning |
|---|---|---|
| `SCT_ADDRESS` | 0 | 0 is broadcast. Use 1 to 99 for one unit |
| `SCT_INIT_ON_START` | `True` | Send the display setup at start. The SCT-50 does not save it |
| `SCT_H_SIZE`, `SCT_V_SIZE` | 1, 2 | Width and height of characters (1 to 4) |
| `SCT_H_POS`, `SCT_V_POS` | 17, 1 | Position (01 to 63). Adjust these values for your picture |
| `SHOW_EVENT_TITLE` | `True` | Show the event name at the top of each page |
| `SCT_PAGE_S` | 8 | Seconds for each page |
| `SCT_DISPLAY_S` | 300 | Seconds until the screen clears. The value 0 means never |
| `SCT_MAX_PAGES` | 12 | Maximum number of pages for one message |
| `SCT_CMD_GAP_MS` | 15 | Pause after each command |
| `SCT_SPACE_BYTE` | `0x09` | Code for a blank. If blanks show as symbols, try `0x20` |
 
---
 
## Operation and log
 
Each log line has this format: `[seconds since start] LEVEL message`. This is an example of a normal alert:
 
```
INFO  RX <- 911: MSG_READY (42 data bytes)
INFO  ALERT HEADER: ZCZC-EAS-NUW-042045+0015-3071135-INTERMOD-
INFO    decoded: NUW = Nuclear Power Plant Warning | from EAS = EAS participant | areas: 042045 | valid 00h15m | issued day 307 11:35 UTC | sender INTERMOD
DEBUG state IDLE -> WAIT_TRANSLATION (requesting translation)
INFO  TX -> 911: TRANSLATION
INFO  RX <- 911: TRANSLATION (165 data bytes)
INFO  TRANSLATION (0.58 s after notice): A NUCLEAR POWER PLANT WARNING HAS BEEN ISSUED ...
INFO  DELIVER: ...
INFO  SCT-50: showing alert in 2 page(s)
INFO  SEQUENCE COMPLETE in 25.2 s
```
 
The adapter writes a `heartbeat` line each `HEARTBEAT_S` seconds. The line shows these counters: bytes, frames, messages, completed, aborted, timeouts, stray and unexpected. If the adapter never receives a byte, it writes one warning. The warning shows what to check.
 
NOTE: The log shows only when Thonny (or a serial terminal) is connected. The board does not keep the log. The time stamps show the time since start. They return to zero after about 12 days.
 
---
 
## Tests without the EAS 911
 
First stop the adapter (push **Stop** or Ctrl+C). Then use the Shell.
 
### Test the decoder and the handshake
 
```python
import main
ep = main.CGEndpoint(print, lambda t, h: main.deliver(t, h, None))
ep.feed(main.frame(7, b"ZCZC-WXR-TOR-042101+0030-3011500-KPHI/NWS-"))
```
 
The log must show the decoded header.
 
### Send a sample alert to the SCT-50
 
```python
import main, time
from machine import UART, Pin
u = UART(1, baudrate=9600, bits=8, parity=None, stop=1, tx=Pin(4), rx=Pin(5), timeout=0)
t = main.SCT50(u.write)
t.init_display()
t.show_alert("Nuclear Power Plant Warning",
    "A NUCLEAR POWER PLANT WARNING HAS BEEN ISSUED FOR THE FOLLOWING COUNTIES/AREAS:\n"
    "DELAWARE PA\nAT 4:35 PM\nON NOV 3, 2026\nEFFECTIVE\nUNTIL 4:50 PM.\nMESSAGE FROM INTERMOD.")
while True:                  # changes pages and clears on time; push Stop to end
    t.service()
    time.sleep_ms(100)
```
 
### Send a complete alert through the adapter
 
Use the variable `t` from the previous test.
 
```python
ep = main.CGEndpoint(print, lambda txt, hdr: main.deliver(txt, hdr, t))
ep.feed(main.frame(7, b"ZCZC-EAS-NUW-042045+0015-3071135-INTERMOD-"))
ep.feed(main.frame(6, b"A NUCLEAR POWER PLANT WARNING ...\nDELAWARE PA\nAT 4:35 PM"))
```
 
NOTE: A setting that you change in the Shell (for example `main.SCT_V_POS = 20`) stays only until the next reset. To keep a setting, edit the file.
 
---
 
## Output drivers
 
### Horita SCT-50 (available)
 
The SCT-50 is a video titler that you control through a serial port. Its screen has 9 lines. Each line has 20 characters. Each command has this format: `ESC` + 2-digit address + 2-digit command + data.
 
The driver does these tasks:
 
- It sets the display at start. It sets the display, background, white characters, no line numbers, no clock, no date, size, position, write enables and clear.
- It shows a title. The title is the event name. It uses a maximum of two lines.
- It divides the alert text into lines of 20 characters.
- It keeps the line breaks of the EAS 911. It keeps a clock time together with AM or PM.
- It divides a long message into pages. It changes the page each `SCT_PAGE_S` seconds.
- It writes all 180 characters for each page. No text from the previous page stays.
- It clears the screen after `SCT_DISPLAY_S` seconds.
- It changes the text to upper case. It replaces characters that the SCT-50 cannot show. The SCT-50 can show `A` to `Z`, `0` to `9` and these characters: `. , ' & : ? ! ~ ( ) / * - + =`.
For the complete command list, see [Horita SCT-50 serial protocol](#horita-sct-50-serial-protocol).
 
Commands that the driver uses: 07 display on, 09 background on, 11 white characters, 14 line numbers off, 20 write to screen, 22 write to memory page, 25 clear, 26 set character pointer, 27 write text, 35 time off, 40 date off, 44 to 47 position and size.
 
Set up the SCT-50:
 
1. Set **ONLINE** to **Y**.
2. Set **BAUD** to the same value as `TARGET_BAUD`.
3. Set **ADDRESS** to 00, or to the same value as `SCT_ADDRESS`.
The LED of the SCT-50 gives this data. A very slow blink shows that there is no video. A quick flash shows that the SCT-50 receives data. In HEX mode, the SCT-50 shows the received bytes on the screen.
 
---
 
## Add support for another CG
 
The adapter does not have a plug-in system at this time. This section shows the planned design. It also shows what an existing driver does that a new driver must copy.
 
### Data for a driver
 
For each alert, a driver receives these data:
 
- The decoded alert text, with the line breaks of the EAS 911.
- The event code and the event name.
- The raw SAME header. A driver can use it to read the areas, the duration or the sender.
### Members of a driver
 
The SCT-50 driver is a class. A new driver must have the same members.
 
| Member | Purpose |
|---|---|
| `__init__(write, dry_run)` | Accepts a function that sends bytes. In dry-run mode, it only writes to the log |
| `init_display()` | Does the device setup one time at start |
| `show_alert(title, text)` | Prepares and shows one alert |
| `service()` | The adapter calls it in each loop. It changes pages and clears the display. It must not stop for a long time |
| `clear()` | Clears the display |
 
### Steps to add a CG
 
1. Find the protocol of the device. Find the character set, the line and column limits and the timing rules.
2. Write a class with the members in the table. Include a dry-run mode that writes the exact bytes to the log. Then you can develop the driver without the device.
3. Put the text clean-up and the line wrap in the driver. Each CG has different limits.
4. Add the settings for the driver near the `SCT_*` constants. Add a switch to select the driver.
5. Test the driver from the Shell with a sample alert. Do this before you connect it to the EAS 911.
### Design goals
 
- Use more than one output at the same time. Each output has its own UART or other transport.
- Select the drivers and the ports in one place.
- Use one message object (title, text, event, areas, header). Then each driver does not decode the header again.
- A failure of one output must not stop the EAS 911 handshake. The handshake has strict time limits: the EAS 911 stops after three tries that are 2 seconds apart.
- Keep the EAS 911 input side independent of each output.
---
 
## Protocol references
 
This project uses two protocols. The TFT protocol is on the input side. The Horita protocol is on the output side. Add a subsection for each new CG driver.
 
### TFT EAS 911 character generator protocol
 
Source: the character generator appendix of the TFT EAS 911 manual.
 
- Interface: RS-232, **9600 baud, 8 data bits, no parity, 1 stop bit**.
- Connector: DB9 (J302). Pin 2 is Rx. Pin 3 is Tx. Pin 5 is GND.
- Frame: `STX (0x02)` + control byte + optional data + `ETX (0x03)`.
| Control byte | Meaning |
|---|---|
| 0x04 | Audio header and attention tone: request or acknowledge |
| 0x05 | Alert voice and audio EOM: request or acknowledge |
| 0x06 | Header translation: request or data |
| 0x07 | Message ready (EAS 911 to CG). The data is the SAME header |
| 0x08 | Last text message: request or data |
| 0x09 | User-recorded voice announcement: request or acknowledge |
| 0x0A | Alert voice only: request or acknowledge |
| 0x0B | Exception (abort or time-out) |
 
Normal sequence:
 
```
911 -> CG : STX 07 <SAME header> ETX      message ready (up to 3 times, 2 seconds apart)
CG  -> 911: STX 06 ETX                    request translation
911 -> CG : STX 06 <text> ETX             plain-English text (can arrive in several parts)
CG  -> 911: STX 04 ETX                    request audio header and attention tone
911 -> CG : STX 04 ETX                    acknowledge when sent
CG  -> 911: STX 05 ETX                    request voice and EOM
911 -> CG : STX 05 ETX                    acknowledge when done
```
 
- If the CG does not answer the first frame, the EAS 911 stops (aborts) the message.
- In manual mode, the last acknowledgement waits until the operator pushes SEND EOM. For this reason `T_VOICE_MS` is long.
### Horita SCT-50 serial protocol
 
Source: *Horita SCT-50 Serial Control Titler User Manual*, Doc. 071550 Rev. D (2014), chapters 3, 4 and 5. The RM-50/SCT and SR-50/SCT models use the same protocol. This section is a summary. For critical work, read the manual.
 
#### Physical link
 
| Item | Data |
|---|---|
| Interface | RS-232, DB9. **SERIAL IN is a female DB9.** **SERIAL OUT is a male DB9.** SERIAL OUT is a loop-through. You can connect up to 99 units in a chain. Each unit in the chain must have power. |
| Cable to a PC | A standard male-to-female, straight-through DB9 cable. The SCT-50 receives data on pin 3. |
| Baud rate | 4800, 9600 or 38.4K. Set it in the SYSTEM SETUP menu. At 38.4K, the byte rate must not be more than one byte for each millisecond. If it is more, the unit loses characters. |
| Data format | The manual gives only the baud rate. This project uses **8 data bits, no parity, 1 stop bit**. This format works on the test unit. |
| Video | Composite NTSC or PAL, 1 V p-p, 75 ohm, BNC input and output. When the unit has no power, the input goes directly to the output. When the unit has power, the input is terminated. **The unit needs a video signal.** |
| Power | 9 to 14 V DC, 150 mA. The connector is a 3.5 mm jack. The center is positive. The unit comes with a 9 V, 500 mA adapter. |
 
#### Command format
 
Each command has this format:
 
```
ESC (0x1B)  +  address (2 ASCII digits)  +  command (2 ASCII digits)  +  optional data
```
 
Example from the manual. This command turns the display off (command 08) for the unit with address 01:
 
```
1B 30 31 30 38        ESC  '0' '1'  '0' '8'
```
 
Rules:
 
- **Address 00** is broadcast. Each SCT-50 obeys the command. Addresses 01 to 99 select one unit.
- A unit that has its own address set to **00** is in "promiscuous" mode. It obeys all commands, with any address.
- An **ESC** character puts all units back into address-compare mode. Then the unit with the correct address stays online until the next ESC.
- A **single-function command** is executed. Then the unit stays in command mode. The manual states that the next command does not need a new ESC and address. This project does not use this function. It sends the full prefix each time.
- A **function/data command** puts the unit in data mode until the next ESC. For variable-length data (text, command 27), the unit processes each character when it arrives. For fixed-length data (positions), the unit does the action each time that the field length is complete.
#### Screen model
 
- The screen has **9 lines of 20 characters**. This gives 180 positions.
- The character pointer (CP) goes from **001** (top left) to **180** (bottom right). The CP increments after each written character.
- The unit has **two memory pages** and the live screen. All pages share the attributes (size, position and color).
- Command 20 enables a write to the screen. Command 22 enables a write to the selected memory page. A write goes to each enabled target.
- In the setup menu, the horizontal and vertical positions are 01 to 64. The commands accept 01 to 63.
- The horizontal size is 1 to 4. The vertical sizes 1X, 2X, 3X and 4X give 7, 14, 28 and 42 video lines for each text line.
- Vertical sizes 5 and 6 (menu "1S" and "2S") are split-screen modes. In these modes, the vertical position sets the amount of split. It does not move the text.
- Typical default menu values: white characters, background on, size H 1X V 2X, position H 17 V 01.
#### Command set
 
`d` is one data character. The last column shows the delay that the manual gives after the command.
 
| Cmd | Data | Function | Wait |
|---|---|---|---|
| 00 | | System reset | 300 ms |
| 03, 04 | | Select time format 3 or 2 (old; command 48 replaces them) | |
| 07 | | Video display on | |
| 08 | | Video display off | |
| 09 | | Background on | |
| 10 | | Background off | |
| 11 | | White characters | |
| 12 | | Black characters | |
| 13 | | Line numbers on | |
| 14 | | Line numbers off | |
| 15 | | Blink mode on (characters with bit 7 set blink) | |
| 16 | | Blink mode off | |
| 17 | `d` 1 to 3 | Contrast: 1 low, 2 medium, 3 high | |
| 18 | | Select memory page 1 | |
| 19 | | Select memory page 2 | |
| 20 | | Enable write to the screen | |
| 21 | | Disable write to the screen | |
| 22 | | Enable write to the selected memory page | |
| 23 | | Disable write to the selected memory page | |
| 24 | `d` 1 to 9 | Clear one line (if write is enabled) | 7 ms |
| 25 | | Clear all lines (if write is enabled) | 100 ms |
| 26 | `ddd` 001 to 180 | Set the character pointer | |
| 27 | `d...` | Write characters at the pointer. The pointer increments. This continues until the next ESC | |
| 28 | `ddd`, then `d` | Set the pointer, write one character, increment the pointer | |
| 29 | | Copy the selected memory page to the screen | 10 ms |
| 30 | | Copy page 1 to page 2 | 150 ms |
| 31 | | Copy page 2 to page 1 and to the screen | 150 ms |
| 32 | | Save the setup values | 7 ms |
| 33 | `d` | Write one character at the pointer. The pointer does not increment | |
| 34, 35 | | Time display on, off | |
| 36 | `hhmmss` | Set the time | |
| 37 | `ddd` 001 to 180 | Start position of the time display | |
| 38 | | Send the time of the SCT-50 to the computer | |
| 39, 40 | | Date display on, off | |
| 41 | `mmddyy` | Set the date | |
| 42 | `ddd` 001 to 180 | Start position of the date display | |
| 43 | | Send the date of the SCT-50 to the computer | |
| 44 | `dd` 01 to 63 | Horizontal position | |
| 45 | `d` 1 to 4 | Horizontal size | |
| 46 | `dd` 01 to 63 | Vertical position | |
| 47 | `d` 1 to 6 | Vertical size (5 and 6 are the split-screen modes) | |
| 48 | `dd` 01 to 36 | Time display format | |
| 49 | `dd` 01 to 60 | Date display format | |
 
Commands 01, 02, 05, 06 and 50 to 99 are not used.
 
#### Character set
 
The unit can show only these characters. Lower-case letters are not available. The table in the manual has **no ASCII space (0x20)**. The code for a blank is 0x09.
 
| Characters | Codes |
|---|---|
| `A` to `Z` | 0x41 to 0x5A |
| `0` to `9` | 0x30 to 0x39 |
| `.` `,` `'` `&` | 0x2E, 0x2C, 0x27, 0x26 |
| `:` `?` `!` | 0x3A, 0x3F, 0x21 |
| `~` `(` `)` `/` `*` `-` `+` `=` | 0x7E, 0x28, 0x29, 0x2F, 0x2A, 0x2D, 0x2B, 0x3D |
| Blank (transparent) | 0x09 |
| White box, black box | 0x01, 0x02 |
| Up, down, left and right arrows | 0x03, 0x04, 0x05, 0x06 |
| Center dot, underscore | 0x07, 0x08 |
 
The manual shows 0x09, 0x01 and 0x02 as space characters. The underscore is in the character cell. It is not below the cell. If blink mode is on (command 15), a character blinks when bit 7 is set.
 
#### Front-panel setup and diagnostics
 
The SYSTEM SETUP menu has these items: **ONLINE** (Y or N; it must be Y for serial control), **ADDRESS** (00 to 99), **MODE** (NOR or HEX), **BAUD**, **SYSTEM RESET** and the **NTSC/PAL** selection.
 
In **HEX mode**, the unit shows the hexadecimal value of each serial byte that it receives. Use this mode to find the data that the controller sends.
 
To do a hardware reset, apply power to the unit while you hold the MODE switch at SETUP.
 
| LED | Meaning |
|---|---|
| Off | No power |
| Steady | Setup or display on/off mode |
| Very slow blink (1 second) | **No video** |
| Slow blink (0.5 second) | Data entry mode |
| Fast blink (0.25 second) | Insert mode |
| Quick flash | **The unit receives serial data** |
 
The manual gives this order for troubleshooting:
 
1. Make sure that ONLINE is set to Y.
2. Make sure that the LED flashes when you send data.
3. Make sure that the address is correct. A quick test is to use address 00.
4. Use HEX mode.
#### Data that this adapter sends
 
At start (`SCT_INIT_ON_START`):
 
```
07 display on     09 background on    11 white characters  14 line numbers off
35 time off       40 date off         45 H size            47 V size
44 H position     46 V position       20 write to screen   22 write to memory page
25 clear
```
 
For each page of an alert, the adapter sends a pointer command. Then it sends all 180 characters. No text from the previous page stays.
 
```
1B 30 30 32 36 30 30 31                ESC "00" "26" "001"   pointer to top left
1B 30 30 32 37 <180 bytes>             ESC "00" "27" + 9 lines x 20 characters, blanks as 0x09
```
 
To clear the screen when the display time ends, the adapter sends `1B 30 30 32 35`.
 
A minimum test from the Pico shell. First make the UART `u` (see [Tests without the EAS 911](#tests-without-the-eas-911)).
 
```python
u.write(b"\x1b0007")                      # display on
u.write(b"\x1b0025")                      # clear all lines (wait 100 ms)
u.write(b"\x1b0026001")                   # pointer to position 001
u.write(b"\x1b0027HELLO")                 # write text
```
 
---
 
## Troubleshooting
 
| Symptom | Cause and action |
|---|---|
| Thonny shows no `>>>` prompt | Push Stop one or two times. Use a USB data cable. Look at the interpreter in the bottom-right corner |
| The board does not show as a drive | This is normal after MicroPython is installed. The board is a COM port. To get the RPI-RP2 drive, hold BOOTSEL when you connect the USB cable |
| The log warns "no bytes received from the 911" | Check menu item 18 (STD). Make sure that the COM expander is installed and Practice mode is off. Check the MAX3232 wiring. Swap TX and RX, or use a null-modem cable |
| Stray bytes or unreadable data | The baud rate is wrong, the ground is bad, or the cable has noise |
| The LED of the SCT-50 does not flash | The data does not arrive. Connect GP4 to GP5 with a wire. Send `hello`. The Pico board must return `b'hello'`. Then measure the idle voltage on pins 2 and 3 of the module DB9. The pin that has about -5 to -10 V is the transmit pin. The SCT-50 receives data on pin 3. If the module sends on pin 2, use a null-modem adapter |
| The LED of the SCT-50 flashes but the screen is blank | Check the composite video input and the monitor. Check that ONLINE is Y. Check the address. Check the position (`SCT_H_POS`, `SCT_V_POS`). Try HEX mode |
| Blanks show as boxes or symbols | Change `SCT_SPACE_BYTE` to `0x20` |
| The text is too high or too low | Change `SCT_V_POS` (01 to 63) |
| The EAS 911 aborts auto-forwarded messages | If STD is selected, the adapter must be on and must answer the EAS 911 |
 
---
 
## Known limits
 
- **Audio during the handshake.** If `COMPLETE_HANDSHAKE` is `True`, the adapter requests the audio header and the voice and EOM. Then the EAS 911 plays its header and attention tone. In one test, this took about 15 seconds. The EAS 911 can also close its on-air relay. Equipment that is connected to these outputs receives the signal. To get only the text, set `COMPLETE_HANDSHAKE` to `False`.
- **Times in translations.** The times come from the clock and the UTC offset of the EAS 911 (menu item 2; +05 for Eastern time in the manual). They do not come from the adapter. If a time is wrong, check the sign of the offset and the DST setting. Also check the clock of the device that made the alert.
- **Firmware and manual.** The firmware of the EAS 911 can be newer than the manual. In one test, the unit translated `NUW`. This code is not in the event table of 1996. The adapter decodes the raw header with the current FCC code list.
- **Time stamps.** The time stamps in the log are the time since start. They return to zero after about 12 days.
- **Log storage.** The board does not keep the log. Keep Thonny or a serial terminal connected to record the log.
- **Header format.** The decoder expects the SAME format: `ZCZC-ORG-EEE-PSSCCC...+TTTT-JJJHHMM-LLLLLLLL-`. If the format is different, the adapter writes a note to the log. It does not stop.
---
 
## Future work
 
- Selection of drivers, and more than one output at the same time.
- More CG drivers. The hardware that is available decides which drivers are made.
- Optional storage of recent alerts on the board, because the log is lost.
- Configuration outside the source file.
- Tests of the other CG interface options of the EAS 911 (CODI, VD1, ALT1, ALT2). They are not in the manual that this project uses.
- More SCT-50 work: tune the layout, and test the cable and character-set assumptions on more hardware.
---
 
## Disclaimer
 
This is an independent hobby project. It is not related to TFT or Horita. It is not certified EAS equipment. EAS equipment is regulated. Incorrect use or modification can have legal results. Keep the outputs disconnected during tests.
 
