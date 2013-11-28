#!/usr/bin/env python

import bEncode as be
import sys, os, time
import urllib, urlparse
import random, math
import string
import weakref, threading, Queue
import hashlib
import bisect
import struct
import traceback
import socket
#import bencode # python bencoder

class obj:
	pass

class queueThread:
	def runloop(self):
		while True:
			try:
				(target, args, kwargs) = self._queue.get()
				if not target:
					return
				target(*args,**kwargs)
			except:
				return

	def __init__(self):
		self.thread = threading.Thread(target=self.runloop)
		self._queue = Queue.Queue()
		self.thread.run()

	def do(target, args = [], kwargs={}):
		self._queue.put((target,args,kwargs))

	def shutdown(self):
		self._queue.put((None,None,None))


#TODO
#reannounce to tracker
#connect to peers

class peer:
	pstr = "BitTorrent protocol"
	# interestingBlocks
	def __init__(self, (ip, port), torrent):
		self.ip = ip
		self.port = port
		self.torrent = weakref.ref(torrent)

		self.unchoked = self.interested = False

		self.readQueue = Queue.Queue()
		self.writeQueue = Queue.Queue()

		self.writeThread = threading.Thread(target=peer.sendThread,args=[weakref.ref(self)])
		self.writeThread.start()
	def __del__(self):
		try: self.skt.close()
		except: pass

	@staticmethod
	def readHandshake(skt):
		protoLen = ord(skt.recv(1))
		protocol = skt.recv(protoLen)
		reserved = skt.recv(8)
		info_hash = skt.recv(20)
		peer_id = skt.recv(20)
		return (protocol, info_hash, peer_id)

	@staticmethod
	def sendThread(selfref):
		try:
			selfref().skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			selfref().skt.connect((selfref().ip, selfref().port))
			selfref().handshake()
			# selfref().bitfield()

			selfref().readThread = threading.Thread(target=peer.recvThread,args=[selfref])
			selfref().readThread.start()
			#tell torrent I've connected
			while True:
				data = selfref().writeQueue.get()
				print len(data),repr(data)
				selfref().skt.send(data)
				selfref().writeQueue.task_done()
		except socket.error, e:
			print 'socket error'
		except Exception, e:
			#tell torrent I've disconnected
			if selfref():
				traceback.print_exc()
				print 'shutting down write queue'

	@staticmethod
	def recvThread(selfref):
		def get(l):
			data = selfref().skt.recv(l,socket.MSG_WAITALL)
			if data and len(data):
				# print selfref().skt.getpeername(),repr(data)
				return data
			else:
				return None
		try:
			try:
				protocol, info_hash, selfref().peer_id = peer.readHandshake(selfref().skt)
			except:
				return

			addr = selfref().skt.getpeername()
			print protocol, addr
			while True:
				data = get(4)
				if not data: continue
				pktLen = struct.unpack('>I',data)[0]
				if pktLen == 0:
					print addr,'keepAlive'
					continue
				pktType = ord(get(1))
				if pktType == 0:
					print addr,'choke'
				elif pktType == 1:
					print addr,'unchoke'
				elif pktType == 2:
					print addr,'interested'
				elif pktType == 3: #uninterested
					print addr,'uninterested'
				elif pktType == 4: #have
					print addr,'have'
					idx = struct.unpack('>I', get(4))[0]
				elif pktType == 5: #bitfield
					print addr,'bitfield'
					bitfield = get(pktLen-1)
				elif pktType == 6: #request
					print addr,'request'
					(idx, pPos, pLen) = struct.unpack('>III', get(12))
				elif pktType == 7: #piece
					print addr,'piece'
					(idx, pPos) = struct.unpack('>II', get(8))
					data = get(pktLen - 9)
				elif pktType == 8: #cancel
					print addr,'cancel'
					(idx, pPos, pLen) = struct.unpack('>III', get(12))
				elif pktType == 9: #port
					print addr,'port'
					port = struct.unpack('>H', get(2))
				else:
					# if pktLen > 0:
						# selfref().skt.recv(pktLen-1)
					print 'unknown packet',pktType
		except socket.error, e:
			print 'socket error'
		except Exception, e:
			if selfref():
				traceback.print_exc()
				print 'shutting down read queue'


	def sendMessage(self,msg=None,payload=''):
		if not msg: data = ''
		else:		data = chr(msg) + payload
		
		self.writeQueue.put(struct.pack('>I',len(data)) + data)

	def handshake(self):
		"send handshake: <pstrlen><pstr><reserved><info_hash><peer_id>"
		self.skt.send(chr(len(peer.pstr)))
		self.skt.send(peer.pstr)
		self.skt.send(chr(0) * 8)
		self.skt.send(self.torrent().info_hash)
		self.skt.send(self.torrent().torrenter().peer_id)

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
	def bitfield(self):
		self.sendMessage(5, self.torrent().packedAvailablePieces())
	def request(self,blk,offset):
		self.sendMessage(6, struct.pack('>III',blk,offset,1<<14)) # use block size of 2^14
	def piece(self,blk,offset,data):
		self.sendMessage(7, struct.pack('>II',blk,offset) + data)
	def cancel(self,blk,offset):
		self.sendMessage(8, struct.pack('>III',blk,offset,1<<14)) # use block size of 2^14

class torrenter:
	lastPort = 6889
	@staticmethod
	def listen(selfref,serverSkt):
		serverSkt.settimeout(1.0)
		skt = None
		while selfref():
			try:
				(skt, addr) = serverSkt.accept()
				#read handshake
				protocol, info_hash, peer_id = peer.readHandshake(skt)
				#
				selfref().torrents[info_hash].newconnection(skt, addr, protocol, peer_id)
			except:
				pass
			finally:
				if skt:
					skt.close()
				skt = None
		serverSkt.close()

	def __init__(self):
		self.peer_id = '-PY0002-' + ''.join(random.choice([chr(i) for i in range(256)]) for x in range(12))
		self.shutdown = False
		self.torrents = {}

		#setup listener
		self.serverSkt = socket.socket(socket.AF_INET)
		for port in range(6880,torrenter.lastPort+1):
			try:
				self.serverSkt.bind(('', port))
				self.port = port
				print 'started on',self.port
				break
			except Exception, e:
				if port == torrenter.lastPort:
					print e
				pass

		#listen on a socket on another thread
		self.serverSkt.listen(5)
		self.listener = threading.Thread(target=torrenter.listen, args=[weakref.ref(self),self.serverSkt])
		self.listener.start()

	def __del__(self):
		self.shutdown = True

	def addTorrent(self,torrent):
		self.torrents[torrent.info_hash] = torrent

	def removeTorrent(self,torrent):
		self.torrents.pop(torrent.info_hash, None)

class torrent:
	def __init__(self,filename,torrenter):
		self.torInfo = be.bDecodeFile(open(filename),raw=True)

		pieces = self.torInfo['info']['pieces']
		size = 160/8
		self.pieceHash = [bytearray(pieces[i*size:(i+1)*size]) for i in range(len(pieces)/size)]
		self.pieceCount = len(self.pieceHash)
		self.pieceAvailable = chr(0)*self.pieceCount #RELOAD

		self.torrenter = weakref.ref(torrenter)
		self.info_hash = hashlib.sha1(self.torInfo['__raw_info']).digest()
		self.peerlist = []
		self.peers = {}

		self.trackerid = None
		self.uploaded = 0	#RELOAD
		self.downloaded = 0	#RELOAD
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

	def packedAvailablePieces(self):
		bitfield = [0] * int(math.ceil(self.pieceCount/8.0))
		for idx, available in enumerate(self.pieceAvailable):
			if available:
				bitfield[idx/8] |= 1<<(7-(idx % 8))
		return ''.join(chr(byte) for byte in bitfield)

	def scrapeURL(self):
		s = self.torInfo['announce']
		if re.match(r'.*/(announce)[^/]*',s).end == len(s):
			return re.sub(r'/announce',r'/scrape',s)
		return None

	def trackerInfo(self,event=''):
		opts = {'info_hash':self.info_hash,
			'peer_id':self.torrenter().peer_id,
			'port':self.torrenter().port,
			'uploaded':self.uploaded,
			'downloaded':self.downloaded,
			'left':self.left,
			'event':event,
			'compact':'1'
			}
		if self.trackerid is not None:
			opts['trackerid'] = self.trackerid
		return urllib.urlencode(opts)

	def newconnection(self, skt, addr, protocol, peer_id):
		print 'peer trying to connect:',addr,protocol,peer_id


	def trackerRequest(self,event='',setpeerlist=True):
		url = self.torInfo['announce'] + '?' + self.trackerInfo(event=event)
		response = be.bDecode(urllib.urlopen(url).read())
		if 'failure reason' in response:
			print 'Tracker returned error',repr(response['failure reason'])
			return

		self.interval = int(response['interval'])
		if 'tracker id' in response:
			self.trackerid = response['tracker id']
		if setpeerlist:
			self.peerlist = response['peers']
			if isinstance(self.peerlist,list):
				self.peerlist = [(peer['ip'], peer['port']) for peer in self.peerlist]
			else: #short format
				self.peerlist = [(
					'.'.join([str(ord(c)) for c in self.peerlist[s:s+4]]),
					ord(self.peerlist[s+4])*256 + ord(self.peerlist[s+5]))
				for s in range(0,len(self.peerlist),6)]


	def start(self):
		self.trackerRequest(event='started')

		#connect to all peers
		num = 0
		for p in self.peerlist:
			num+=1
			self.peers[p[0]] = peer(p,self)
			if num > 10:
				break


		#choose top # peers
		#find lowest block they have which I want
		# start downloading from top list of peers
		#
		#Choking algorithm
		# top 4/5 downloaders who are interested
		#
		#Interested algorithm
		# find everywhere I'm not choked
		# request slice

	def announce(self):
		self.trackerRequest()
	def stop(self):
		self.trackerRequest(event='stopped',setpeerlist=False)
	
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

			# print '  ',repr(filename), f.tell(),blkStart,sectionLen

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
		elif pieceRange[1] > self.length:
			pieceRange[1] = self.length

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

		if False: #test reading and writing
			for i in range(9,-1,-1):
				tor.writeBlock(i,str(i) * tor.info['piece length'])
			for i in range(0,10,2):	
				arr = tor.readBlock(i)
				print arr[:10], arr[-10:]

		tor.start()
		# connection = peerManagement(t, tor)
		# connection.toString()
		raw_input('Press [Enter] to quit\n')
		print 'shutting down (%d)'%threading.activeCount()
		tor.stop()
		del t
	elif len(sys.argv) == 3:
		with open(sys.argv[2]) as f:
			url = f.read()
		print torrent.magnetLink(url)
		print urllib.urlencode({4:torrent.magnetLink(url)['hash']})
	sys.exit()

