import bEncode as be
import sys


def openTorrentFile(filename):
	torInfo = be.bDecodeFile(open(filename))
	pieces = torInfo['info']['pieces']
	size = 160/8
	torInfo['info']['pieces'] = [bytearray(pieces[i*size:(i+1)*size]) for i in range(len(pieces)/size)]
	be.printBencode(torInfo)


if __name__ == "__main__":
	if len(sys.argv) == 2:
		openTorrentFile(sys.argv[1])