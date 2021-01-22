#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" toorsimtool.py: A toolkit for the Toorcamp SIM cards

	Requires the pySim libraries (http://cgit.osmocom.org/cgit/pysim/)
"""

#
# Copyright (C) 2012  Karl Koscher <supersat@cs.washington.edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# December 2014, Dieter Spaar: add OTA security for sysmoSIM SJS1
# December 2019, Dieter Spaar: sysmocom ISIM

from pySim.commands import SimCardCommands
from pySim.utils import swap_nibbles, rpad, b2h, i2h, h2i
try:
	import argparse
except Exception, err:
	print "Missing argparse -- try apt-get install python-argparse"
import zipfile
import time
import struct
import binascii

# Python Cryptography Toolkit (pycrypto)

from Crypto.Cipher import DES3

#------

def hex_ber_length(data):
	dataLen = len(data) / 2
	if dataLen < 0x80:
		return '%02x' % dataLen
	dataLen = '%x' % dataLen
	lenDataLen = len(dataLen)
	if lenDataLen % 2:
		dataLen = '0' + dataLen
		lenDataLen = lenDataLen + 1
	return ('%02x' % (0x80 + (lenDataLen / 2))) + dataLen

class AppLoaderCommands(object):
	def __init__(self, transport):
		self._tp = transport
		self._apduCounter = 0;

	def test_rfm(self):

		# use only one of the following

		if (1):
			# SIM: select MF/GSM/EF_IMSI and read content (requires keyset two)
			if not args.smpp:
				print self.send_wrapped_apdu_rfm_sim('A0A40000023F00' + 'A0A40000027F20' + 'A0A40000026F07' + 'A0B0000009');
			else:
				self.send_wrapped_apdu_rfm_sim('A0A40000023F00' + 'A0A40000027F20' + 'A0A40000026F07' + 'A0B0000009');
		else:
			# USIM: select MF/GSM/EF_IMSI and read content (requires keyset three)
			if not args.smpp:
				print self.send_wrapped_apdu_rfm_usim('00A40004023F00' + '00A40004027F20' + '00A40004026F07' + '00B0000009');
			else:
				self.send_wrapped_apdu_rfm_usim('00A40004023F00' + '00A40004027F20' + '00A40004026F07' + '00B0000009');

		return;

	def send_terminal_profile(self):
		rv = self._tp.send_apdu('8010000011FFFF000000000000000000000000000000')
		if "91" == rv[1][0:2]:
			# In case of "91xx" -> Fetch data, execute cmd and reply
			self._tp.send_apdu('80120000' + rv[1][2:4]) # FETCH
			# otherwise "9300" (SIM Busy)
			return self._tp.send_apdu('801400000C810301030002028281030100') # TERMINAL RESPONSE
		return rv;

	def select_usim(self):
		rv = self._tp.send_apdu('00A4040007a0000000871002')
		return rv;

	# Wrap an APDU inside an SMS-PP APDU	
	def send_wrapped_apdu_internal(self, data, tar, msl, kic_index, kid_index):
		#
		# See ETSI TS 102 225 and ETSI TS 102 226 for more details 
		# about OTA security.
		#
		# So far only no signature check, RC or CC are supported.
		# The only supported ciphering mode is "Triple DES in outer-CBC
		# mode using two different keys" which is also used for CC.

		# SPI first octet: set to MSL
		spi_1 = msl;

		# length of signature

		if ((spi_1 & 0x03) == 0): # no integrity check		
			len_sig = 0;
		elif ((spi_1 & 0x03) == 1): # RC
			len_sig = 4;
		elif ((spi_1 & 0x03) == 2): # CC
			len_sig = 8;
		else:
			print "Invalid spi_1"
			exit(0);
					
		pad_cnt = 0;
		# Padding if Ciphering is used
		if ((spi_1 & 0x04) != 0): # check ciphering bit
			len_cipher = 6 + len_sig + (len(data) / 2)
			pad_cnt = 8 - (len_cipher % 8) # 8 Byte blocksize for DES-CBC (TODO: different padding)
			# TODO: there is probably a better way to add "pad_cnt" padding bytes
			for i in range(0, pad_cnt):
				data = data + '00';

		# CHL + SPI first octet
		part_head = ('%02x' % (0x0D + len_sig)) + ('%02x' % (spi_1))

		Kic = '00';
		KID = '00';
		if ((spi_1 & 0x04) != 0): # check ciphering bit
			Kic = ('%02x' % (0x05 + (kic_index << 4))) # 05: Triple DES in outer-CBC mode using two different keys
		if ((spi_1 & 0x03) == 2): # CC
			KID = ('%02x' % (0x05 + (kid_index << 4))) # 05: Triple DES in outer-CBC mode using two different keys

		# SPI second octet (01: POR required) + Kic + KID + TAR
		# TODO: depending on the returned data use ciphering (10) and/or a signature (08)
		part_head = part_head + '01' + Kic + KID + tar;

		# CNTR + PCNTR (CNTR not used)
		part_cnt = '0000000000' + ('%02x' % (pad_cnt))
		
		envelopeData = part_head + part_cnt + data;
		
		# two bytes CPL, CPL is part of RC/CC/DS
		envelopeData = ('%04x' % (len(envelopeData) / 2 + len_sig)) + envelopeData

		if (len_sig == 8):		
			# Padding 
			temp_data = envelopeData
			len_cipher = (len(temp_data) / 2)
			pad_cnt = 8 - (len_cipher % 8) # 8 Byte blocksize for DES-CBC  (TODO: add different padding)
			# TODO: there is probably a better way to add "pad_cnt" padding bytes
			for i in range(0, pad_cnt):
				temp_data = temp_data + '00';
			
			key = binascii.a2b_hex(args.kid);
			iv = binascii.a2b_hex('0000000000000000');
			cipher = DES3.new(key, DES3.MODE_CBC, iv);
			ciph = cipher.encrypt(binascii.a2b_hex(temp_data));
			envelopeData = part_cnt + binascii.b2a_hex(ciph[len(ciph) - 8:]) + data;
		elif (len_sig == 4):		
			crc32 = binascii.crc32(binascii.a2b_hex(envelopeData))
			envelopeData = part_cnt + ('%08x' % (crc32 & 0xFFFFFFFF)) + data;
		elif (len_sig == 0):		
			envelopeData = part_cnt + data;
		else:
			print "Invalid len_sig"
			exit(0)
		
		# Ciphering (CNTR + PCNTR + RC/CC/DS + data)
		
		if ((spi_1 & 0x04) != 0): # check ciphering bit
			key = binascii.a2b_hex(args.kic);
			iv = binascii.a2b_hex('0000000000000000');
			cipher = DES3.new(key, DES3.MODE_CBC, iv);				
			ciph = cipher.encrypt(binascii.a2b_hex(envelopeData));					
			envelopeData = part_head + binascii.b2a_hex(ciph)		
		else:
			envelopeData = part_head + envelopeData;
		
		# -------------------------------------------------------------
		
		# Command (add UDHI: USIM Toolkit Security Header)
		# TS 23.048
		#
		#   02: UDHDL 
		#   70: IEIA (CPI=70)
		#   00: IEIDLa
		# 
		# two bytes CPL
		# no CHI
		# 
		envelopeData = '027000' + ('%04x' % (len(envelopeData) / 2)) + envelopeData;

		# For sending via SMPP, those are the data which can be put into
		# the "hex" field of the "sendwp" XML file (see examples in libsmpp34).

		if args.smpp:
			print "SMPP: " + envelopeData;
			return ('00', '9000');

		# SMS-TDPU header: MS-Delivery, no more messages, TP-UD header, no reply path,
		# TP-OA = TON/NPI 55667788, TP-PID = SIM Download, BS timestamp
		envelopeData = '400881556677887ff600112912000004' + ('%02x' % (len(envelopeData) / 2)) + envelopeData;

		# (82) Device Identities: (83) Network to (81) USIM
		# (8b) SMS-TPDU 
		envelopeData = '820283818B' + hex_ber_length(envelopeData) + envelopeData
		
		# d1 = SMS-PP Download, d2 = Cell Broadcast Download
		envelopeData = 'd1' + hex_ber_length(envelopeData) + envelopeData;
		# APDU "ENVELOPE"
		(response, sw) = self._tp.send_apdu('80c20000' + ('%02x' % (len(envelopeData) / 2)) + envelopeData)
		if "9e" == sw[0:2]: # more bytes available, get response
			response = self._tp.send_apdu_checksw('80C00000' + sw[2:4])[0] # APDU "GET RESPONSE"

		# no wrapped response !?!
		if (len(response) == 0):
			return (response, sw)
		# Unwrap response
		response = response[(int(response[10:12],16)*2)+12:]
		return (response[6:], response[2:6])

	def send_wrapped_apdu_ram(self, data):
		if (len(args.kic) == 0) and (len(args.kid) == 0):
			#  TAR RAM: 000000, no security (JLM SIM)
			return self.send_wrapped_apdu_internal(data, '000000', 0, 0, 0)
		else:
			# TAR RAM: 000000, sysmoSIM SJS1: MSL = 6, first keyset
			# TAR RAM: 000000, sysmocom ISIM: MSL = 6, third keyset
			return self.send_wrapped_apdu_internal(data, '000000', 6, args.ram_kic_id, args.ram_kid_id)

	def send_wrapped_apdu_rfm_sim(self, data):
		# TAR RFM SIM:  B00010, sysmoSIM SJS1: MSL = 6, second keyset
		return self.send_wrapped_apdu_internal(data, 'B00010', 6, 2, 2)

	def send_wrapped_apdu_rfm_usim(self, data):
		# TAR RFM USIM: B00011, sysmoSIM SJS1: MSL = 6, third keyset
		return self.send_wrapped_apdu_internal(data, 'B00011', 6, 3, 3)

	def send_wrapped_apdu_checksw(self, data, sw="9000"):
		response = self.send_wrapped_apdu_ram(data)
		if response[1] != sw:
			raise RuntimeError("SW match failed! Expected %s and got %s." % (sw.lower(), response[1]))
		return response

	def get_security_domain_aid(self):
		# Get Status followed by Get Response
		response = self.send_wrapped_apdu_checksw('80F28000024F0000C0000000')[0]
		return response[2:(int(response[0:2],16)*2)+2]

	def delete_aid(self, aid, delete_related=True):
		aidDesc = '4f' + ('%02x' % (len(aid) / 2)) + aid
		apdu = '80e400' + ('80' if delete_related else '00') + ('%02x' % (len(aidDesc) / 2)) + aidDesc + '00c0000000'
		return self.send_wrapped_apdu_checksw(apdu)

	def load_aid_raw(self, aid, executable, codeSize, volatileDataSize = 0, nonvolatileDataSize = 0):
		#print "-- codeSize = %d (0x%X)" % (codeSize, codeSize)

		loadParameters = 'c602' + ('%04x' % codeSize)
		if volatileDataSize > 0:
			loadParameters = loadParameters + 'c702' ('%04x' % volatileDataSize)
		if nonvolatileDataSize > 0:
			loadParameters = loadParameters + 'c802' ('%04x' % nonvolatileDataSize)
		loadParameters = 'ef' + ('%02x' % (len(loadParameters) / 2)) + loadParameters
		
		# Install for load APDU, no security domain or hash specified
		data = ('%02x' % (len(aid) / 2)) + aid + '0000' + ('%02x' % (len(loadParameters) / 2)) + loadParameters + '0000'
		self.send_wrapped_apdu_checksw('80e60200' + ('%02x' % (len(data) / 2)) + data + '00c0000000')

		# Load APDUs
		loadData = 'c4' + hex_ber_length(executable) + executable
		loadBlock = 0
		sizeSent = 0
		sizeLoadData = len(loadData) / 2

		# print "-- size loadData = %d (0x%X)" % (sizeLoadData, sizeLoadData)

		blockSize = 0x88; # in hex chars

		# print "-- blockSize in bytes = %d (0x%X)" % (blockSize / 2, blockSize / 2)

		while len(loadData):
			loadBlockSent = loadBlock
			if len(loadData) > blockSize:
				size = blockSize / 2
				# APDU "LOAD"
				apdu = '80e800' + ('%02x' % loadBlock) + ('%02x' % (blockSize / 2)) + loadData[:blockSize]
				loadData = loadData[blockSize:]
				loadBlock = loadBlock + 1
			else:
				size = len(loadData) / 2
				# APDU "LOAD for last block"
				apdu = '80e880' + ('%02x' % loadBlock) + ('%02x' % (len(loadData) / 2)) + loadData
				loadData = ''

			sizeSent = sizeLoadData - (len(loadData) / 2)
			# print "-- loadBlock = %d  sizeSent = %d (0x%X)  size = %d (0x%X)" % (loadBlockSent, sizeSent, sizeSent, size, size)

			self.send_wrapped_apdu_checksw(apdu + '00c0000000')
	
	def generate_load_file(self, capfile):
		zipcap = zipfile.ZipFile(capfile)
		zipfiles = zipcap.namelist()

		header = None
		directory = None
		impt = None
		applet = None
		clas = None
		method = None
		staticfield = None
		export = None
		constpool = None
		reflocation = None

		for i, filename in enumerate(zipfiles):
			if filename.lower().endswith('header.cap'):
				header = zipcap.read(filename)
			elif filename.lower().endswith('directory.cap'):
				directory = zipcap.read(filename)
			elif filename.lower().endswith('import.cap'):
				impt = zipcap.read(filename)
			elif filename.lower().endswith('applet.cap'):
				applet = zipcap.read(filename)
			elif filename.lower().endswith('class.cap'):
				clas = zipcap.read(filename)
			elif filename.lower().endswith('method.cap'):
				method = zipcap.read(filename)
			elif filename.lower().endswith('staticfield.cap'):
				staticfield = zipcap.read(filename)
			elif filename.lower().endswith('export.cap'):
				export = zipcap.read(filename)
			elif filename.lower().endswith('constantpool.cap'):
				constpool = zipcap.read(filename)
			elif filename.lower().endswith('reflocation.cap'):
				reflocation = zipcap.read(filename)

		data = header.encode("hex")
		if directory:
			data = data + directory.encode("hex")
		if impt:
			data = data + impt.encode("hex")
		if applet:
			data = data + applet.encode("hex")
		if clas:
			data = data + clas.encode("hex")
		if method:
			data = data + method.encode("hex")
		if staticfield:
			data = data + staticfield.encode("hex")
		if export:
			data = data + export.encode("hex")
		if constpool:
			data = data + constpool.encode("hex")
		if reflocation:
			data = data + reflocation.encode("hex")

		return data

	def get_aid_from_load_file(self, data):
		return data[26:26+(int(data[24:26],16)*2)]
		 
	def load_app(self, capfile):
		data = self.generate_load_file(capfile)
		aid = self.get_aid_from_load_file(data)
		self.load_aid_raw(aid, data, len(data) / 2)

	def install_app(self, args):
		loadfile = self.generate_load_file(args.install)
		aid = self.get_aid_from_load_file(loadfile)

		toolkit_params = ''
		if args.enable_sim_toolkit:
			assert len(args.access_domain) % 2 == 0
			assert len(args.priority_level) == 2
			toolkit_params = ('%02x' % (len(args.access_domain) / 2))  + args.access_domain
			toolkit_params = toolkit_params + args.priority_level + ('%02x' % args.max_timers)
			toolkit_params = toolkit_params + ('%02x' % args.max_menu_entry_text)
			toolkit_params = toolkit_params + ('%02x' % args.max_menu_entries) + '0000' * args.max_menu_entries + '0000'
			if args.tar:
				assert len(args.tar) % 6 == 0
				toolkit_params = toolkit_params + ('%02x' % (len(args.tar) / 2)) + args.tar
			toolkit_params = 'ca' + ('%02x' % (len(toolkit_params) / 2)) + toolkit_params

		assert len(args.nonvolatile_memory_required) == 4
		assert len(args.volatile_memory_for_install) == 4
		parameters = 'c802' + args.nonvolatile_memory_required + 'c702' + args.volatile_memory_for_install
		if toolkit_params:
			parameters = parameters + toolkit_params
		parameters = 'ef' + ('%02x' % (len(parameters) / 2)) + parameters + 'c9' + ('%02x' % (len(args.app_parameters) / 2)) + args.app_parameters
		
		data = ('%02x' % (len(aid) / 2)) + aid + ('%02x' % (len(args.module_aid) / 2)) + args.module_aid + ('%02x' % (len(args.instance_aid) / 2)) + \
			   args.instance_aid + '0100' + ('%02x' % (len(parameters) / 2)) + parameters + '00'
		self.send_wrapped_apdu_checksw('80e60c00' + ('%02x' % (len(data) / 2)) + data + '00c0000000')
#------

parser = argparse.ArgumentParser(description='Tool for Toorcamp SIMs.')
parser.add_argument('-s', '--serialport')
parser.add_argument('-p', '--pcsc', nargs='?', const=0, type=int)
parser.add_argument('-d', '--delete-app')
parser.add_argument('-l', '--load-app')
parser.add_argument('-i', '--install')
parser.add_argument('--module-aid')
parser.add_argument('--instance-aid')
parser.add_argument('--nonvolatile-memory-required', default='0000')
parser.add_argument('--volatile-memory-for-install', default='0000')
parser.add_argument('--enable-sim-toolkit', action='store_true')
parser.add_argument('--access-domain', default='ff')
parser.add_argument('--priority-level', default='01')
parser.add_argument('--max-timers', type=int, default=0)
parser.add_argument('--max-menu-entry-text', type=int, default=16)
parser.add_argument('--max-menu-entries', type=int, default=0)
parser.add_argument('--app-parameters', default='')
parser.add_argument('--print-info', action='store_true')
parser.add_argument('-n', '--new-card-required', action='store_true')
parser.add_argument('-z', '--sleep_after_insertion', type=float, default=0.0)
parser.add_argument('--disable-pin')
parser.add_argument('--pin')
parser.add_argument('-t', '--list-applets', action='store_true')
parser.add_argument('--tar')
parser.add_argument('--dump-phonebook', action='store_true')
parser.add_argument('--set-phonebook-entry', nargs=4)
parser.add_argument('--kic', default='')
parser.add_argument('--kid', default='')
parser.add_argument('--ram-kic-id', default=1)
parser.add_argument('--ram-kid-id', default=1)
parser.add_argument('--smpp', action='store_true')
parser.add_argument('--test', action='store_true')
parser.add_argument('--aram-apdu', default='')

args = parser.parse_args()

if args.pcsc is not None:
	from pySim.transport.pcsc import PcscSimLink
	sl = PcscSimLink(args.pcsc)
elif args.serialport is not None:
	from pySim.transport.serial import SerialSimLink
	sl = SerialSimLink(device=args.serialport, baudrate=9600)
else:
	raise RuntimeError("Need to specify either --serialport or --pcsc")

sc = SimCardCommands(sl)
ac = AppLoaderCommands(sl)

if not args.smpp:
	sl.wait_for_card(newcardonly=args.new_card_required)
	time.sleep(args.sleep_after_insertion)

if not args.smpp:
	# Get the ICCID
	# print "ICCID: " + swap_nibbles(sc.read_binary(['3f00', '2fe2'])[0])
	ac.select_usim()
	ac.send_terminal_profile()

if len(args.aram_apdu) > 0:
	# Select the ARA-M applet from its AID
	aram_rv = rv = ac._tp.send_apdu('00A4040009A00000015141434C00')
	if '9000' != aram_rv[1]:
		raise RuntimeError("SW match failed! Expected %s and got %s." % ('9000', aram_rv[1]))
	# Add/Delete Access rules list in ARA-M
	rv = ac._tp.send_apdu(args.aram_apdu)
	if '9000' != rv[1] and '6a88' != rv[1]:
		raise RuntimeError("SW match failed! Expected %s and got %s." % ('9000', rv[1]))
	if '80CAFF4000' == args.aram_apdu:
		res = h2i(rv[0])
		n = 0
		# REF-AR-DO - Tag value is E2 - Search for starting point of certificate
		while res[n] != 0xe2:
			n += 1
		i = 1
		total_len = len(res[n:])
		while n <= total_len:
			# Additional 2 bytes for REF-AR-DO Tag value E2 and length byte
			cert_len = res[n+1:n+2][0] + 2
			cert = ['%02x'% x for x in res[n:n+cert_len]]
			print "Certificate " + str(i) + ": " + ''.join(cert)
			i += 1
			n += cert_len

# for RFM testing 
#ac.test_rfm()
#exit(0)

if args.pin:
	sc.verify_chv(1, args.pin)

if args.delete_app:
	ac.delete_aid(args.delete_app)

if args.load_app:
	ac.load_app(args.load_app)

if args.install:
	ac.install_app(args)

if args.print_info:
	print "--print-info not implemented yet."

if args.disable_pin:
	sl.send_apdu_checksw('0026000108' + args.disable_pin.encode("hex") + 'ff' * (8 - len(args.disable_pin)))

if args.dump_phonebook:
	num_records = sc.record_count(['3f00','7f10','6f3a'])
	print ("Phonebook: %d records available" % num_records)
	for record_id in range(1, num_records + 1):
		print sc.read_record(['3f00','7f10','6f3a'], record_id)

if args.set_phonebook_entry:
	num_records = sc.record_count(['3f00','7f10','6f3a'])
	record_size = sc.record_size(['3f00','7f10','6f3a'])
	record_num = int(args.set_phonebook_entry[0])
	if (record_num < 1) or (record_num > num_records):
		raise RuntimeError("Invalid phonebook record number")
	encoded_name = rpad(b2h(args.set_phonebook_entry[1]), (record_size - 14) * 2)
	if len(encoded_name) > ((record_size - 14) * 2):
		raise RuntimeError("Name is too long")
	if len(args.set_phonebook_entry[2]) > 20:
		raise RuntimeError("Number is too long")
	encoded_number = swap_nibbles(rpad(args.set_phonebook_entry[2], 20))
	record = encoded_name + ('%02x' % len(args.set_phonebook_entry[2])) + args.set_phonebook_entry[3] + encoded_number + 'ffff'
	sc.update_record(['3f00','7f10','6f3a'], record_num, record)

if args.list_applets:
	(data, status) = ac.send_wrapped_apdu_ram('80f21000024f0000c0000000')
	while status == '6310':
		(partData, status) = ac.send_wrapped_apdu_ram('80f21001024f0000c0000000')
		data = data + partData

	while len(data) > 0:
		aidlen = int(data[0:2],16) * 2
		aid = data[2:aidlen + 2]
		state = data[aidlen + 2:aidlen + 4]
		privs = data[aidlen + 4:aidlen + 6]
		num_instances = int(data[aidlen + 6:aidlen + 8], 16)
		print 'AID: ' + aid + ', State: ' + state + ', Privs: ' + privs
		data = data[aidlen + 8:]
		while num_instances > 0:
			aidlen = int(data[0:2],16) * 2
			aid = data[2:aidlen + 2]
			print "\tInstance AID: " + aid
			data = data[aidlen + 2:]
			num_instances = num_instances - 1

if args.test:
	print 'Test'
	#(data, status) = ac.send_wrapped_apdu_ram('A0A4040009A00000015141434C0000')
	#(data, status) = ac.send_wrapped_apdu_ram('00A4040009A00000015141434C0000')
	(data, status) = ac.send_wrapped_apdu_ram('80E2900033F031E22FE11E4F06FFFFFFFFFFFFC114E46872F28B350B7E1F140DE535C2A8D5804F0BE3E30DD00101DB080000000000000001')
	print 'Data: ' + data
	print 'SW: ' + status
