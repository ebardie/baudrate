#!/usr/bin/env python

import sys
import time
import serial
from threading import Thread

class RawInput:
    """Gets a single character from standard input.  Does not echo to the screen."""
    def __init__(self):
        try:
            self.impl = RawInputWindows()
        except ImportError:
            self.impl = RawInputUnix()

    def __call__(self): return self.impl()


class RawInputUnix:
    def __init__(self):
        import tty, sys

    def __call__(self):
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch


class RawInputWindows:
    def __init__(self):
        import msvcrt

    def __call__(self):
        import msvcrt
        return msvcrt.getch()

class Baudrate:

    VERSION = '1.0'
    READ_TIMEOUT = 5
    BAUDRATES = [
            "921600",
            "576000",
            "460800",
            "230400",
            "115200",
            "76800",
            "57600",
            "38400",
            "28800",
            "19200",
            "9600",
            "4800",
            "2400",
            "1800",
            "1200",
            "600",
            "300",
            "200",
            "150",
            "134",
            "110",
            "75",
            "50",
    ]

    MAX_LEN = len(max(BAUDRATES, key=len))

    DEFAULT_BAUDRATE = "115200"

    CONTROL_A  = '\x01'
    CONTROL_B  = '\x02'
    CONTROL_C  = '\x03'
    INTERPRET_MODE_KEY = CONTROL_B
    ESCAPE_KEY = '\x1b'
    ESCAPE_CODE_COMING = '[' # e.g. ESC + this + A == up arrow
    INTERPRET_ESC_TIMEOUT_MS = 100

    UPKEYS = ['u', 'U', 'A']
    DOWNKEYS = ['d', 'D', 'B']
    HELPKEYS = ['h', '?']
    RETURN = ['\n', '\r']

    MIN_CHAR_COUNT = 25
    WHITESPACE = [' ', '\t', '\r', '\n']
    PUNCTUATION = ['.', ',', ':', ';', '?', '!']
    VOWELS = ['a', 'A', 'e', 'E', 'i', 'I', 'o', 'O', 'u', 'U']

    def __init__(self, port=None, threshold=MIN_CHAR_COUNT, timeout=READ_TIMEOUT, name=None, auto=True, verbose=False, allow_newline=False, passthrough_keys=False, toggle_baud=DEFAULT_BAUDRATE):
        self.port = port
        self.threshold = threshold
        self.timeout = timeout
        self.name = name
        self.auto_detect = auto
        self.verbose = verbose
        self.index = self.BAUDRATES.index(self.DEFAULT_BAUDRATE)
        self.valid_characters = []
        self.ctlc = False
        self.thread = None
        self.buffer = ""
        self.max_display_chars = 80 # The widespread 80 column archaism should be fine
        self.newline_sub = f"\r{' ' * self.max_display_chars}\r"
        self.stderr_needs_capping = False
        self.allow_newline = allow_newline
        self.passthrough_keys = passthrough_keys
        index = self.BAUDRATES.index(toggle_baud)
        self.toggle_bauds = (index, index)

        self._gen_char_list()

    def _gen_char_list(self):
        c = ' '

        while c <= '~':
            self.valid_characters.append(c)
            c = chr(ord(c) + 1)

        for c in self.WHITESPACE:
            if c not in self.valid_characters:
                self.valid_characters.append(c)

    def cap_stderr(self):
        sys.stderr.write('\n\n')
        self.stderr_needs_capping = False

    def _print(self, data, allow_newline=False):
        if self.verbose:
            try:
                buf = data.decode('utf-8')
                reprinting = True
                if allow_newline or self.allow_newline:
                    if '\n' in buf:
                        reprinting = False
                    self.buffer += buf
                else:
                    if '\n' in buf:
                        if '\n' == buf:  # Just a newline char
                            self.buffer = self.newline_sub
                            return  # Don't leave a blank line
                        else:  #  Embedded newline(s)
                            buf = buf.strip()  # Don't leave a blank line
                            if '\n' in buf:
                                pos = buf.rfind('\n')
                                self.buffer = self.newline_sub + buf[pos + 1:]
                            else:
                                self.buffer = buf
                    else:
                        self.buffer += buf

                if self.stderr_needs_capping:
                    self.cap_stderr()

                prefix = '\r' if reprinting else ""
                sys.stderr.write(f"{prefix}{self.buffer}")

                if len(self.buffer) >= self.max_display_chars or not prefix:
                    self.buffer = ""
            except:
                pass

    def Open(self):
        self.serial = serial.Serial(self.port, timeout=self.timeout)
        self.NextBaudrate(0)

    def set_baud_from_index(self, index=None):
        self.index = index if index else self.index

        if not self.stderr_needs_capping:
            sys.stderr.write('\n\n')
            self.stderr_needs_capping = True

        sys.stderr.write(f"\r@@@@@@@@@@@@@@@@@@@@@ Baudrate: {self.BAUDRATES[self.index]:>{Baudrate.MAX_LEN}} @@@@@@@@@@@@@@@@@@@@@")

        self.serial.flush()
        self.serial.baudrate = self.BAUDRATES[self.index]
        self.serial.flush()

    def NextBaudrate(self, updn):

        self.index -= updn

        if self.index >= len(self.BAUDRATES):
            self.index = 0
        elif self.index < 0:
            self.index = len(self.BAUDRATES) - 1

        self.set_baud_from_index()

    def Detect(self):
        count = 0
        whitespace = 0
        punctuation = 0
        vowels = 0
        start_time = 0
        timed_out = False
        clear_counters = False

        if not self.auto_detect:
            self.thread = Thread(None, self.HandleKeypress, None, (self, 1))
            self.thread.start()

        while True:
            if start_time == 0:
                start_time = time.time()

            byte = self.serial.read(1)

            if byte:
                if self.auto_detect and byte in self.valid_characters:
                    if byte in self.WHITESPACE:
                        whitespace += 1
                    elif byte in self.PUNCTUATION:
                        punctuation += 1
                    elif byte in self.VOWELS:
                        vowels += 1

                    count += 1
                else:
                    clear_counters = True

                self._print(byte)

                if count >= self.threshold and whitespace > 0 and punctuation > 0 and vowels > 0:
                    break
                elif (time.time() - start_time) >= self.timeout:
                    timed_out = True
            else:
                timed_out = True

            if timed_out and self.auto_detect:
                start_time = 0
                self.NextBaudrate(-1)
                clear_counters = True
                timed_out = False

            if clear_counters:
                whitespace = 0
                punctuation = 0
                vowels = 0
                count = 0
                clear_counters = False

            if self.ctlc:
                break

        self._print("\n", allow_newline=True)
        return self.BAUDRATES[self.index]

    def toggle_baud(self):
        prev_index = self.toggle_bauds[0]
        next_index = self.toggle_bauds[1]
        if self.index != next_index:
            prev_index = self.index
            self.set_baud_from_index(next_index)
        self.toggle_bauds = (next_index, prev_index)

    def HandleKeypress(self, *args):
        userinput = RawInput()

        interpret_mode = not self.passthrough_keys

        interpret_esc_timeout = 0

        while not self.ctlc:
            c = userinput()

            # The Escape value has been detected, and that could indicate:
            #    exit interpret_mode
            # or
            #    if within the timeout period it MAY be followed by a value indicating an escape code
            if interpret_esc_timeout:
                now =  time.time() * 1000
                if now < interpret_esc_timeout:
                    if c == self.ESCAPE_CODE_COMING:
                        interpret_mode = True
                        interpret_esc_timeout = 0
                        continue
                interpret_esc_timeout = 0

            if self.passthrough_keys and not interpret_mode:
                passthrough = True
                if c == self.INTERPRET_MODE_KEY:
                    if not interpret_mode:
                        interpret_mode = True;
                        continue

                if passthrough:
                    self.serial.write(bytes(c, 'UTF-8'))

            if interpret_mode:
                if c in self.UPKEYS:
                    self.NextBaudrate(1)
                elif c in self.DOWNKEYS:
                    self.NextBaudrate(-1)
                elif c in self.HELPKEYS:
                    self.help_keys()
                elif c == ' ':
                    self.toggle_baud()
                elif c in self.RETURN:
                    if self.stderr_needs_capping:
                        self.cap_stderr()
                    sys.stderr.write('\n')
                elif c == self.CONTROL_C:
                    self.ctlc = True
                elif c == self.ESCAPE_KEY and self.passthrough_keys:
                    interpret_esc_timeout = time.time() * 1000 + self.INTERPRET_ESC_TIMEOUT_MS
                    interpret_mode = False
                    continue

                if self.passthrough_keys:
                    interpret_mode = False

    def prefix_char(self):
        return chr(ord('A') + ord(self.INTERPRET_MODE_KEY[0]) - 1)

    def help_keys(self):
        prefix = f"CTRL-{self.prefix_char()}"

        if self.stderr_needs_capping:
            self.cap_stderr()

        print(f"""Keys:
        {prefix} when in key press passthrough mode for this programme to process the following keypresses.
        ESC to cancel {prefix}.
        ↑ and ↓ arrow keys or 'u' and 'd' to increment/decrement the baudrate.
        h to display this helpful information.
        SPACE to toggle between recent baudrates.
        CTRL-C to break out from this programme.
        """, file=sys.stderr)

    def MinicomConfig(self, name=None):
        success = True

        if name is None:
            name = self.name

        config =  "########################################################################\n"
        config += "# Minicom configuration file - use \"minicom -s\" to change parameters.\n"
        config += "pu port             %s\n" % self.port
        config += "pu baudrate         %s\n" % self.BAUDRATES[self.index]
        config += "pu bits             8\n"
        config += "pu parity           N\n"
        config += "pu stopbits         1\n"
        config += "pu rtscts           No\n"
        config += "########################################################################\n"

        if name is not None and name:
            try:
                open("/etc/minicom/minirc.%s" % name, "w").write(config)
            except Exception as e:
                if self.stderr_needs_capping:
                    self.cap_stderr()
                print("Error saving minicom config file:", str(e))
                success = False

        return (success, config)

    def Close(self):
        self.ctlc = True
        self.serial.close()



if __name__ == '__main__':

    import subprocess
    from getopt import getopt as GetOpt, GetoptError

    def usage():
        baud = Baudrate()

        print("")
        print("Baudrate v%s" % baud.VERSION)
        print("Craig Heffner, http://www.devttys0.com")
        print("")
        print("Usage: %s [OPTIONS]" % sys.argv[0])
        print("")
        print("\t-p <serial port>       Specify the serial port to use [/dev/ttyUSB0]")
        print("\t-t <seconds>           Set the timeout period used when switching baudrates in auto detect mode [%d]" % baud.READ_TIMEOUT)
        print("\t-c <num>               Set the minimum ASCII character threshold used during auto detect mode [%d]" % baud.MIN_CHAR_COUNT)
        print("\t-n <name>              Save the resulting serial configuration as <name> and automatically invoke minicom (implies -a)")
        print("\t-a                     Enable auto detect mode")
        print("\t-b                     Display supported baud rates and exit")
        print("\t-q                     Do not display data read from the serial port")
        print("\t-v                     Don't suppress newline in display data read from the serial port")
        print(f"\t-k                     Passthough keypresses to serial connexion. Use CTRL-{baud.prefix_char()} as prefix key to control app.")
        print("\t-T <baud>              Toggle between current value and the given baud when SPACE is pressed")
        print("\t-h                     Display help")
        print("")
        sys.exit(1)

    def display_baudrates(msg=None):
        if msg:
            print(f"{msg}")
        print()
        for rate in Baudrate.BAUDRATES:
            print("\t%s" % rate)
        print()

    def main():
        display = False
        verbose = True
        allow_newline = False
        auto = False
        run = False
        threshold = 25
        timeout = 5
        name = None
        port = '/dev/ttyUSB0'
        toggle_baud = Baudrate.DEFAULT_BAUDRATE
        passthrough_keys = False

        try:
              (opts, args) = GetOpt(sys.argv[1:], 'p:t:c:n:abqvkT:h')
        except GetoptError as e:
            print(e)
            usage()

        for opt, arg in opts:
            if opt == '-t':
                timeout = int(arg)
            elif opt == '-c':
                threshold = int(arg)
            elif opt == '-p':
                port = arg
            elif opt == '-n':
                name = arg
                auto = True
                run = True
            elif opt == '-a':
                auto = True
            elif opt == '-b':
                display = True
            elif opt == '-q':
                verbose = False
                allow_newline = False
            elif opt == '-v':
                verbose = True
                allow_newline = True
            elif opt == '-k':
                passthrough_keys = True
            elif opt == '-T':
                toggle_baud = arg
                try:
                    index = Baudrate.BAUDRATES.index(toggle_baud)
                except ValueError:
                    display_baudrates(f"Can't find '{toggle_baud}' baud in list:")
                    sys.exit(1)
            else:
                usage()

        baud = Baudrate(port, threshold=threshold, timeout=timeout, name=name, verbose=verbose, auto=auto, allow_newline=allow_newline, passthrough_keys=passthrough_keys, toggle_baud=toggle_baud)

        if display:
            display_baudrates()
        else:
            if not passthrough_keys:
                print("")
                print("Starting baudrate detection on %s, turn on your serial device now." % port)
                print("Press Ctl+C to quit.")
                print("")

            baud.Open()

            try:
                rate = baud.Detect()
            except KeyboardInterrupt:
                pass

            baud.Close()

            if not passthrough_keys:
                print("\nDetected baudrate: %s" % rate)

                if name is None:
                    print("\nSave minicom configuration as: ",)
                    name = sys.stdin.readline().strip()
                    print("")

                (ok, config) = baud.MinicomConfig(name)
                if name and name is not None:
                    if ok:
                        if not run:
                            print("Configuration saved. Run minicom now [n/Y]? ",)
                            yn = sys.stdin.readline().strip()
                            print("")
                            if yn == "" or yn.lower().startswith('y'):
                                run = True

                        if run:
                            subprocess.call(["minicom", name])
                    else:
                        print(config)
                else:
                    print(config)

    main()
