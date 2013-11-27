#!/usr/bin/env python

import bEncode as be
import sys, os
import urllib, urlparse
import random
import string
import weakref
import hashlib
import bisect
import struct
#import bencode # python bencoder

class peer:
	pstr = "BitTorrent protocol"
	def __init__(self, ip, port):
		self.ip = ip
		self.port = port
		self.hash = torrentHash

	def sendMessage(self,msg=None,payload=''):
		def _send(data):
			self.skt.send(struct.pack('>I',len(data)))
			self.skt.send(data)
		if not msg:
			self.skt.send('')
		else:
			self.skt.send(chr(ord('0')+msg) + payload)

	def handshake(self,info_hash,peer_id):
		"send handshake <pstrlen><pstr><reserved><info_hash><peer_id>"
		self.skt.send(chr(len(peer.pstr)))
		self.skt.send(peer.pstr)
		self.skt.send(chr(0) * 8)
		self.skt.send(info_hash)
		self.skt.send(peer_id)

	def keepAlive(self): #every 2 minutes
		self.sendMessage()
	def choke(self):
		self.sendMessage(0)
	def unchoke(self):
		self.sendMessage(1)
	def interested(self):
		self.sendMessage(2)
	def uninterested(self):
		self.sendMessage(3)
	def have(self,index):
		self.sendMessage(4, struct.pack('>I',len(index)))
	def bitfield(self,bitfield):
		self.sendMessage(5, bitfield)
	def request(self,blk,offset):
		self.sendMessage(6, struct.pack('>III',blk,offset,1<<14)) # use block size of 2^14
	def piece(self,blk,offset,data):
		self.sendMessage(7, struct.pack('>II',blk,offset) + data)
	def cancel(self,blk,offset):
		self.sendMessage(7, struct.pack('>II',blk,offset,1<<14)) # use block size of 2^14


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
		self.peer_id = '-PY0002-' + ''.join(random.choice([chr(i) for i in range(256)]) for x in range(12))
		self.port = 0

	def addTorrent(self,torrent):
		pass

	def removeTorrent(self,torrent):
		pass

class torrent:
	def __init__(self,filename,torrenter):
		self.torInfo = be.bDecodeFile(open(filename),raw=True)

		pieces = self.torInfo['info']['pieces']
		size = 160/8
		self.torInfo['info']['pieces'] = [bytearray(pieces[i*size:(i+1)*size]) for i in range(len(pieces)/size)]

		self.torrenter = weakref.ref(torrenter)

		self.trackerid = None
		self.uploaded = 0
		self.downloaded = 0
		self.fileStart = [0]
		self.fileLen = []
		self.info = self.torInfo['info']
		if 'files' in self.info: #mutlifile mode
			for f in self.info['files']:
				self.fileLen.append(f['length'])
				self.fileStart.append(self.fileStart[-1] + f['length'])
			self.length = self.left = self.fileStart[-1]
			self.folder = self.info['name']
		else: #singlefile mode
			self.length = self.left = self.info['length']
			self.fileLen.append(self.length)
			self.folder = None

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

	
	def file(self,idx):
		"returns the relative path of the file number idx in the torrent"
		path = []
		if self.folder:
			path.append(self.folder)
		path.extend(self.info['files'][idx]['path'])
		return os.path.join(*path)

	def blockRange(self,blkNum):
		#bounds check
		if blkNum >= len(self.info['pieces']) or blkNum < 0:
			return (0,0)

		# get position
		blkLen = self.info['piece length']
		pieceStart = blkLen * blkNum
		if blkNum == len(self.info['pieces']) - 1:
			blkLen = ((self.length - 1) % blkLen) + 1
		pieceEnd = pieceStart + blkLen

		return (pieceStart, pieceEnd)


	def pieceCallback(self,(pieceStart,pieceEnd),callback,*info):
		"""
		A block spans multiple files, so for block: blkNum
		Calls callback(filename, fileStart, blkStart, sectionLen, *info)
		on each section of the block from the corresponding files
		"""
		blkStart = 0
		blkLen = pieceEnd - pieceStart

		#find correct file
		idx = bisect.bisect_right(self.fileStart, pieceStart) - 1

		fileStart = pieceStart - self.fileStart[idx]
		while blkStart < blkLen:
			if self.fileLen[idx] - fileStart < blkLen - blkStart:
				sectionLen = self.fileLen[idx] - fileStart
			else:
				sectionLen = blkLen - blkStart
			callback(self.file(idx),fileStart,blkStart,sectionLen, *info)

			#next file (spilled over current file)
			blkStart += sectionLen
			fileStart = 0
			idx += 1

	def writeBlock(self,blkNum,data, pieceRange=None):
		"Write data to the block number in the torrent (no error checking yet)"
		# print 'write block',blkNum
		def w(filename,fileStart,blkStart,sectionLen):
			parent = os.path.dirname(filename)
			if not os.path.exists(parent):	
				os.makedirs(parent)

			if not os.path.exists(filename):
				f = open(filename,'w')
			else:
				f = open(filename,'r+')
			f.seek(fileStart,0)

			print '  ',repr(filename), f.tell(),blkStart,sectionLen

			f.write(data[blkStart:blkStart+sectionLen])
			f.close()

		if pieceRange is None:
			pieceRange = self.blockRange(blkNum)

		self.pieceCallback(pieceRange, w)

	def readBlock(self,blkNum, pieceRange=None):
		"Read data from the block number in the torrent (no error checking yet)"
		data = bytearray()
		def r(filename,fileStart,blkStart,sectionLen):
			f = open(filename,'r')
			f.seek(fileStart,0)
			data.extend(f.read(sectionLen))

		if pieceRange is None:
			pieceRange = self.blockRange(blkNum)

		self.pieceCallback(pieceRange, r)
		return data

	@staticmethod
	def magnetLink(url):
		d = urlparse.parse_qs(urlparse.urlparse(url)[4])

		xtns = 'urn:btih:'
		if d['xt'][0].startswith(xtns):
			return {'name':d['dn'][0], 'trackers':d['tr'], 'hash':d['xt'][0][len(xtns):].decode('hex')}
		return None


if __name__ == "__main__":
	"python __ filename.torrent"
	"python __ -m magnetlink"
	t = torrenter()
	if len(sys.argv) == 2:
		tor = torrent(sys.argv[1],t)
		# be.printBencode(tor.torInfo)
		print urllib.urlencode({4:hashlib.sha1(tor.torInfo['__raw_info']).digest()})

		if True: #test reading and writing
			for i in range(9,-1,-1):
				tor.writeBlock(i,str(i) * tor.info['piece length'])
			for i in range(0,10,1):	
				arr = tor.readBlock(i)
				print arr[:10], arr[-10:]
		# tor.start()
		# connection = peerManagement(t, tor)
		# connection.toString()
		# tor.stop()
	elif len(sys.argv) == 3:
		with open(sys.argv[2]) as f:
			url = f.read()
		print torrent.magnetLink(url)
		print urllib.urlencode({4:torrent.magnetLink(url)['hash']})

