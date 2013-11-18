import bEncode as be
import sys
import urllib
import random
import string
import weakref
import hashlib
#import bencode # python bencoder

#John - multifile support, magnet links
class peerManagement:
	"""A class for the managing of peer connections"""
	def __init__(self, torrenter, torrent):
		url = torrent.torInfo['announce'] + '?' + torrent.trackerInfo(event='started')
		response = urllib.urlopen(url)
		self.trackerData = be.bDecode(response.read())['peers'] # using project implemented bencoder
#		self.trackerData = bencode.bdecode(response.read())['peers'] # using python bencoder
		for peer in self.trackerData:
			peer['am_choking'] = 1
			peer['am_interested'] = 0
			peer['p_choking'] = 1
			peer['p_interested'] = 0
		torrent.stop()

	def toString(self):
		"""Print out the peer related data"""
		for peer in self.trackerData:
			for k,v in peer.iteritems():
				print k, v
			print "\n" 

class torrenter:
	def __init__(self):
		self.peer_id = '-PY0001-' + ''.join(random.choice([chr(i) for i in range(256)]) for x in range(12))
		self.port = 0

	def addTorrent(self,torrent):
		pass

	def removeTorrent(self,torrent):
		pass

class torrent:
	def __init__(self,filename,torrenter):
		self.torInfo = be.bDecodeFile(open(filename))
		pieces = self.torInfo['info']['pieces']
		size = 160/8
		self.torInfo['info']['pieces'] = [bytearray(pieces[i*size:(i+1)*size]) for i in range(len(pieces)/size)]

		self.torrenter = weakref.ref(torrenter)

		self.trackerid = None
		self.uploaded = 0
		self.downloaded = 0
		self.left = self.torInfo['info']['length']

	def scrapeURL(self):
		s = self.torInfo['announce']
		if re.match(r'.*/(announce)[^/]*',s).end == len(s):
			return re.sub(r'/announce',r'/scrape',s)
		return None

	def trackerInfo(self,event=''):
		# need port, uploaded, downloaded, left, compact, event
		opts = {'info_hash':hashlib.sha1(self.torInfo['__raw_info']).digest(),
			'peer_id':self.torrenter().peer_id,
			'port':self.torrenter().port,
			'uploaded':self.uploaded,
			'downloaded':self.downloaded,
			'left':self.left,
			'event':event
			#,'compact':'1'
			}
		if self.trackerid is not None:
			opts['trackerid'] = self.trackerid
		return urllib.urlencode(opts)

	def start(self):
		url = self.torInfo['announce'] + '?' + self.trackerInfo(event='started')
		response = urllib.urlopen(url)
		be.printBencode(be.bDecode(response.read()))

	def stop(self):
		url = self.torInfo['announce'] + '?' + self.trackerInfo(event='stopped')
		response = urllib.urlopen(url)
		be.printBencode(be.bDecode(response.read()))

	def writeBlock(self,blkNum,data):
		pass

	def readBlock(self,blkNum):
		pass

if __name__ == "__main__":
	t = torrenter()
	if len(sys.argv) == 2:
		tor = torrent(sys.argv[1],t)
		be.printBencode(tor.torInfo)
		tor.start()
		connection = peerManagement(t, tor)
		connection.toString()
		tor.stop()
