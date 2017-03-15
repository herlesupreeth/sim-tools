# Shadytel SIM Tools

## Creating JavaCard STK Applets

Use the hello-stk example to get started.

	$ mkdir javacard
	$ cd javacard
	$ git clone https://git.osmocom.org/sim/sim-tools
	$ git clone https://git.osmocom.org/sim/hello-stk
	$ cd hello-stk
	$ make
	
To install the applet onto a SIM card, first set the type of reader you are using.

	# For PCSC readers:
    $ export SHADYSIM_OPTIONS="--pcsc"

	# For USB-serial readers:
    $ export SHADYSIM_OPTIONS="--serialport /dev/ttyUSB0"

and follow instructions at https://osmocom.org/projects/cellular-infrastructure/wiki/Shadysimpy
    
The shadysim tool has lots of other options.

    $ ./sim-tools/bin/shadysim --help
