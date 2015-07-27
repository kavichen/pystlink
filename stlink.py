import sys
import stlinkusb
import stlinkv2
import stlinkex


PARTNO = {
    0xc20: {
        'type': 'CortexM0',
        'DBGMCU_IDCODE_addr': 0x40015800,
    },
    0xc24: {
        'type': 'CortexM4',
        'DBGMCU_IDCODE_addr': 0xE0042000,
    },
}

DEV_ID = {
    0x413: {
        'type': 'STM32F405/407/415/417',
        'sram_start': 0x20000000,
        'sram_size': 192 * 1024,
        'flash_start': 0x08000000,
        'flashsize_reg': 0x1fff7a22,
        'flashpagesize': None,
    },
    0x419: {
        'type': 'STM32F42x/43x',
        'sram_start': 0x20000000,
        'sram_size': 256 * 1024,
        'flash_start': 0x08000000,
        'flashsize_reg': 0x1fff7a22,
        'flashpagesize': None,
    },
    # # this MCU will be detected as STM32F05x
    # 0x440: {
    #     'type': 'STM32F030x8',
    # 'sram_start': 0x20000000,
    #     'sram_size': 8 * 1024,
    #     'flashsize_reg': 0x1ffff7cc,
    # },
    0x440: {
        'type': 'STM32F05x',
        'sram_start': 0x20000000,
        'sram_size': 8 * 1024,
        'flash_start': 0x08000000,
        'flashsize_reg': 0x1ffff7cc,
        'flashpagesize': 1024,
    },
    0x444: {
        'type': 'STM32F03x',
        'sram_start': 0x20000000,
        'sram_size': 4 * 1024,
        'flash_start': 0x08000000,
        'flashsize_reg': 0x1ffff7cc,
        'flashpagesize': 1024,
    },
    0x445: {
        'type': 'STM32F04x',
        'sram_start': 0x20000000,
        'sram_size': 6 * 1024,
        'flash_start': 0x08000000,
        'flashsize_reg': 0x1ffff7cc,
        'flashpagesize': 1024,
    },
    0x448: {
        'type': 'STM32F07x',
        'sram_start': 0x20000000,
        'sram_size': 16 * 1024,
        'flash_start': 0x08000000,
        'flashsize_reg': 0x1ffff7cc,
        'flashpagesize': 2 * 1024,
    },
}

REGISTERS = ['R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9', 'R10', 'R11', 'R12', 'SP', 'LR', 'PC']


class Stlink(stlinkv2.StlinkV2):
    def __init__(self, **kwds):
        super().__init__(**kwds)
        self._ver_stlink = None
        self._ver_jtag = None
        self._ver_swim = None
        self._ver_api = None
        self._voltage = None
        self._coreid = None
        self._cpuid = None
        self._idcode = None
        self._partno = None
        self._dev_id = None

    def read_version(self):
        ver = self.get_version()
        self._ver_stlink = (ver >> 12) & 0xf
        self._ver_jtag = (ver >> 6) & 0x3f
        self._ver_swim = ver & 0x3f
        self._ver_api = 2 if self._ver_jtag > 11 else 1
        self.debug("STLINK: V%d.J%d.S%d (API:v%d)" % (self._ver_stlink, self._ver_jtag, self._ver_swim, self._ver_api), level=2)

    def read_target_voltage(self):
        self._voltage = self.get_target_voltage()
        self.debug("SUPPLY: %.2fV" % self._voltage, 1)

    def read_coreid(self):
        self._coreid = self.get_coreid()
        self.debug("COREID: %08x" % self._coreid, 2)
        if self._coreid == 0:
            raise stlinkex.StlinkException('Not connected to CPU')

    def read_cpuid(self):
        self._cpuid = self.get_debugreg(0xe000ed00)
        self._partno = 0xfff & (self._cpuid >> 4)
        self.debug("CPUID: %08x" % self._cpuid, 2)
        if self._partno not in PARTNO:
            raise stlinkex.StlinkException('CORE id:0x%03x is not supported' % self._partno)
        self.debug("CORE: %s" % PARTNO[self._partno]['type'], 1)

    def read_idcode(self):
        self._idcode = self.get_debugreg(PARTNO[self._partno]['DBGMCU_IDCODE_addr'])
        self._dev_id = 0xfff & self._idcode
        self.debug("IDCODE: %08x" % self._idcode, 2)
        if self._dev_id not in DEV_ID:
            raise stlinkex.StlinkException('CPU is not supported')
        self.debug("CPU: %s" % DEV_ID[self._dev_id]['type'], 1)
        self.debug("SRAM: %dKB" % (DEV_ID[self._dev_id]['sram_size'] / 1024), 1)

    def read_flashsize(self):
        self._flashsize = self.get_debugreg16(DEV_ID[self._dev_id]['flashsize_reg']) * 1024
        self.debug("FLASH: %dKB" % (self._flashsize // 1024), 1)

    def core_halt(self):
        self.set_debugreg(0xe000edf0, 0xa05f0003)

    def core_run(self):
        self.set_debugreg(0xe000edf0, 0xa05f0001)

    def core_nodebug(self):
        self.set_debugreg(0xe000edf0, 0xa05f0000)

    def detect(self, cputype=None):
        self.read_version()
        self.set_swd_freq(1800000)
        self.enter_debug_swd()
        self.read_coreid()
        self.read_cpuid()
        self.read_idcode()
        self.read_flashsize()
        self.read_target_voltage()

    def disconnect(self):
        self.core_nodebug()
        self.leave_state()

    def dump_registers(self):
        self.core_halt()
        for i in range(len(REGISTERS)):
            print("  %3s: %08x" % (REGISTERS[i], self.get_reg(i)))

    def read_mem(self, addr, size, block_size=1024):
        if size <= 0:
            return addr, []
        data = []
        blocks = size // block_size
        if size % block_size:
            blocks += 1
        iaddr = addr
        for i in range(blocks):
            if (i + 1) * block_size > size:
                block_size = size - (block_size * i)
            block = self.get_mem32(iaddr, block_size)
            data.extend(block)
            iaddr += block_size
        return (addr, data)

    def print_mem(self, mem, bytes_per_line=16):
        addr, data = mem
        prev_chunk = []
        same_chunk = False
        for i in range(0, len(data), bytes_per_line):
            chunk = data[i:i + bytes_per_line]
            if prev_chunk != chunk:
                print('  %08x  %s' % (addr, ' '.join(['%02x' % d for d in chunk])))
                prev_chunk = chunk
                same_chunk = False
            elif not same_chunk:
                print('  *')
                same_chunk = True
            addr += bytes_per_line

    def read_sram(self):
        return self.read_mem(DEV_ID[self._dev_id]['sram_start'], DEV_ID[self._dev_id]['sram_size'])

    def read_flash(self):
        return self.read_mem(DEV_ID[self._dev_id]['flash_start'], self._flashsize)

if __name__ == "__main__":
    if not sys.argv[1:]:
        print("ST-LinkV2 for python, (c)2015 by pavel.revak@gmail.com")
        print()
        print("usage:")
        print("  %s [commands ...]" % sys.argv[0])
        print()
        print("commands:")
        print("  verbose:{level} - set verbose level from 0 - minimal to 3 - maximal")
        print("  cpu[:{cputype}] - connect and detect CPU, set cputype for expected, eg: STM32F051R8 (this is not implemented yet)")
        print("  dump:registers - print all registers")
        print("  dump:flash - print content of FLASH memory")
        print("  dump:sram - print content of SRAM memory")
        print("  dump:mem:{addr}:{size} - print content of memory")
        print("  dump:reg:{addr} - print content of 32 bit register")
        print("  dump:reg16:{addr} - print content of 16 bit register")
        print("  dump:reg8:{addr} - print content of 8 bit register")
        print()
        print("example:")
        print("  %s verbose:1 cpu dump:flash dump:sram, dump:registers, dump:reg:0xe000ed00" % sys.argv[0])
    try:
        stlink = Stlink(verbose=0)
        for arg in sys.argv[1:]:
            subargs = arg.split(':')
            if subargs[0] == 'verbose' and len(subargs) > 1:
                stlink.set_verbose(int(subargs[1]))
            elif subargs[0] == 'cpu':
                cpu = None
                if len(subargs) > 1:
                    cpu = subargs[1]
                stlink.detect(cpu)
            elif subargs[0] == 'dump' and len(subargs) > 1:
                if stlink._dev_id is None:
                    raise stlinkex.StlinkException('CPU is not selected')
                if subargs[1] == 'registers':
                    stlink.dump_registers()
                elif subargs[1] == 'flash':
                    mem = stlink.read_flash()
                    stlink.print_mem(mem)
                elif subargs[1] == 'sram':
                    mem = stlink.read_sram()
                    stlink.print_mem(mem)
                elif subargs[1] == 'mem' and len(subargs) > 3:
                    mem = stlink.read_mem(int(subargs[2], 0), int(subargs[3], 0))
                    stlink.print_mem(mem)
                elif (subargs[1] == 'reg' or subargs[1] == 'reg32') and len(subargs) > 2:
                    addr = int(subargs[2], 0)
                    reg = stlink.get_debugreg(addr)
                    print('  %08x: %08x' % (addr, reg))
                elif subargs[1] == 'reg16' and len(subargs) > 2:
                    addr = int(subargs[2], 0)
                    reg = stlink.get_debugreg16(addr)
                    print('  %08x: %04x' % (addr, reg))
                elif subargs[1] == 'reg8' and len(subargs) > 2:
                    addr = int(subargs[2], 0)
                    reg = stlink.get_debugreg8(addr)
                    print('  %08x: %02x' % (addr, reg))
                else:
                    print('*** Bad subparam: "%s" ***' % arg)
                    break
            else:
                print('*** Bad param: "%s" ***' % arg)
                break
        if stlink._dev_id is not None:
            stlink.disconnect()
        stlink.debug('DONE', 2)
    except stlinkex.StlinkException as e:
        print(e)
