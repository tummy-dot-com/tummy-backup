#!/usr/bin/env python
#
#  Load postgres connect string from config file.
#  File should be a single line of the form:
#
#  	dbname=tummybackup user=USERNAME host=127.0.0.1 password=PASSWORD


import os

def loadConnectString():
	for filename in [
			'/etc/tummybackup/dbconnect',
			'/usr/local/lib/tummybackup/conf/dbconnect',
			]:
		if os.path.exists(filename):
			fp = open(filename, 'r')
			line = fp.readline().strip()
			fp.close()
			return(line)

	#  default
	return('dbname=tummybackup')

connectString = loadConnectString()
