// license:BSD-3-Clause
/***************************************************************************

    Z80 + Z80 SIO/0 serial test machine (minimal driver)

    Memory map:
        0000-1FFF  ROM (bootloader.bin)
        2000-FFFF  RAM

    mame 8bits_56k -video none -sound none -rs232a null_modem -bitb socket.127.0.0.1:4000

***************************************************************************/

#include "emu.h"

#include "bus/rs232/rs232.h"
#include "cpu/z80/z80.h"
#include "machine/clock.h"
#include "machine/z80sio.h"


namespace {

class sioserial_state : public driver_device
{
public:
	sioserial_state(const machine_config &mconfig, device_type type, const char *tag) :
		driver_device(mconfig, type, tag),
		m_maincpu(*this, "maincpu"),
		m_sio(*this, "sio")
	{ }

	void sioserial(machine_config &config);

private:
	void mem_map(address_map &map) ATTR_COLD;
	void io_map(address_map &map) ATTR_COLD;

	required_device<z80_device> m_maincpu;
	required_device<z80sio_device> m_sio;
};


void sioserial_state::mem_map(address_map &map)
{
	map(0x0000, 0x1fff).rom().region("maincpu", 0);
	map(0x2000, 0xffff).ram();
}

void sioserial_state::io_map(address_map &map)
{
	map.global_mask(0xff);
	map(0x00, 0x00).rw(m_sio, FUNC(z80sio_device::da_r), FUNC(z80sio_device::da_w));
	map(0x01, 0x01).rw(m_sio, FUNC(z80sio_device::db_r), FUNC(z80sio_device::db_w));
	map(0x02, 0x02).rw(m_sio, FUNC(z80sio_device::ca_r), FUNC(z80sio_device::ca_w));
	map(0x03, 0x03).rw(m_sio, FUNC(z80sio_device::cb_r), FUNC(z80sio_device::cb_w));
}

static const z80_daisy_config daisy_chain[] =
{
	{ "sio" },
	{ nullptr }
};

[[maybe_unused]] static INPUT_PORTS_START( sioserial )
INPUT_PORTS_END

static DEVICE_INPUT_DEFAULTS_START( null_modem_115200 )
	DEVICE_INPUT_DEFAULTS( "RS232_TXBAUD", 0xff, RS232_BAUD_115200 )
	DEVICE_INPUT_DEFAULTS( "RS232_RXBAUD", 0xff, RS232_BAUD_115200 )
DEVICE_INPUT_DEFAULTS_END

void sioserial_state::sioserial(machine_config &config)
{
	constexpr XTAL CPU_CLOCK = XTAL(3'686'400);
	constexpr int  BAUD      = 115200;

	Z80(config, m_maincpu, CPU_CLOCK);
	m_maincpu->set_addrmap(AS_PROGRAM, &sioserial_state::mem_map);
	m_maincpu->set_addrmap(AS_IO, &sioserial_state::io_map);
	m_maincpu->set_daisy_config(daisy_chain);

	// Z80 SIO/0
	Z80SIO(config, m_sio, CPU_CLOCK);
	m_sio->out_int_callback().set_inputline(m_maincpu, INPUT_LINE_IRQ0);
	m_sio->out_txda_callback().set("rs232a", FUNC(rs232_port_device::write_txd));
	m_sio->out_dtra_callback().set("rs232a", FUNC(rs232_port_device::write_dtr));
	m_sio->out_rtsa_callback().set("rs232a", FUNC(rs232_port_device::write_rts));

	// RS232 port, channel A. null_modem is the device that talks to -bitb
	rs232_port_device &rs232a(RS232_PORT(config, "rs232a", default_rs232_devices, "null_modem"));
	rs232a.set_option_device_input_defaults("null_modem", DEVICE_INPUT_DEFAULTS_NAME(null_modem_115200));
	rs232a.rxd_handler().set(m_sio, FUNC(z80sio_device::rxa_w));
	rs232a.dcd_handler().set(m_sio, FUNC(z80sio_device::dcda_w));
	rs232a.cts_handler().set(m_sio, FUNC(z80sio_device::ctsa_w));

	// Tx/Rx clock for channel A: baud rate x16 (WR4 is set to x16 mode)
	clock_device &sioclk(CLOCK(config, "sioclk", BAUD * 32));
	sioclk.signal_handler().set(m_sio, FUNC(z80sio_device::txca_w));
	sioclk.signal_handler().append(m_sio, FUNC(z80sio_device::rxca_w));
}


ROM_START( 8bits_56k )
	ROM_REGION( 0x2000, "maincpu", 0 )
	ROM_LOAD( "bootloader.bin", 0x0000, 0x00FF, CRC(707992cf) SHA1(c851ef0bf8b25242e55ed95258e03b3ebac009f1) )
ROM_END

} // anonymous namespace


//    YEAR  NAME       PARENT  COMPAT  MACHINE    INPUT      CLASS            INIT        COMPANY  FULLNAME                         FLAGS
COMP( 2026, 8bits_56k, 0,      0,      sioserial, sioserial, sioserial_state, empty_init, "",      "Z80 + SIO/0. 8k ROM + 56k RAM", MACHINE_NO_SOUND_HW )
