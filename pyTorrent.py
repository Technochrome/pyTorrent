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
from test_win import *

def _log(level, *args):
	msg = ' '.join(str(arg) for arg in args)
	logQueue.put((level,msg))
	# print msg

def log(*args): _log(2,*args)
def logWarn(*args): _log(3,*args)
def logErr (*args): _log(1,*args)
def logInfo(*args): _log(6,*args)

def blkUpdate(blk,color=2):
	logQueue.put((color,blk))

logQueue = Queue.Queue()

class obj:
	pass

class runloop:
	@staticmethod
	def runloop(selfref):
		while True:
			try:
				(target, args, kwargs) = selfref()._queue.get()
				if not target:
					return
				try:
					target(*args,**kwargs)
				except: pass
					# traceback.print_exc()
			except:
				return

	def __init__(self):
		self.thread = threading.Thread(target=runloop.runloop, args=[weakref.ref(self)])
		self._queue = Queue.Queue()
		self.thread.start()

	def do(self, target, args = [], kwargs={}):
		self._queue.put((target,args,kwargs))

	def shutdown(self):
		self._queue.put((None,None,None))

	def __del__(self):
		self.shutdown()

class repeatTimer:
	def __init__(self, interval, action, args=[], kwargs={}):
		self.stop = False
		self.timer = threading.Timer(interval, self.execute, [interval, action, args, kwargs])
		self.timer.start()
	def execute(self,interval,action,args,kwargs):
		action(*args,**kwargs)
		if not self.stop:
			self.timer = threading.Timer(interval, self.execute, [interval, action, args, kwargs])
			self.timer.start()
	def cancel(self):
		self.stop = True
		self.timer.cancel()
	def __del__(self):
		self.cancel()


class pieceBitfield:
	def __init__(self, pieces=0, bitfield=None):
		if bitfield:
			self.bytes = bytearray(bitfield)
		else:
			self.bytes = bytearray([0])*int(math.ceil(pieces/8.0))

	def set(self, bytes):
		if len(self.bytes) == len(bytes):
			self.bytes = bytearray(bytes)

	def __len__(self):
		return len(self.bytes)*8

	def __getitem__(self,key):
		return (self.bytes[key/8] << (key % 8)) & 0x80

	def __setitem__(self,key,value):
		if value:
			self.bytes[key/8] |= (0x80 >> (key % 8))
		else:
			self.bytes[key/8] &= (0xff7f >> (key % 8))

	def __str__(self):
		return "".join("%02x" % b for b in self.bytes)


mainLoop = runloop()

#TODO
#reannounce to tracker

class peer:
	pstr = "BitTorrent protocol"
	def __init__(self, (ip, port), torrent):
		self.ip = ip
		self.port = port
		self.torrent = weakref.ref(torrent)

		self._choked = self.choking = True
		self.interested = self._interesting = False

		self.pieceAvailable = pieceBitfield(torrent.pieceCount)
		self.interestingBlocks = set()

		self.readQueue = Queue.Queue()
		self.writeQueue = Queue.Queue()

		self.writeThread = threading.Thread(target=peer.readWriteThread,args=[weakref.ref(self)],name='%s write'%ip)
		self.writeThread.start()

		self.downloadingBlock = None
		self.partialBlockData = bytearray()
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
	def readWriteThread(selfref):
		try:
			established = hasattr(selfref(),'skt')
			if not established:
				try:
					selfref().skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
					selfref().skt.connect((selfref().ip, selfref().port))
				except:
					# print 'connection failed', selfref().ip, selfref().port
					#tell torrent I've disconnected
					try: mainLoop.do(selfref().torrent().disconnection, [(selfref().ip, selfref().port)])
					except: pass
					return

			selfref().handshake()
			addr = selfref().skt.getpeername()

			def recv():
				def get(l):
					if l <= 0: return None
					return selfref().skt.recv(l,socket.MSG_WAITALL)
				try:
					if not established:
						try: protocol, info_hash, selfref().peer_id = peer.readHandshake(selfref().skt)
						except: 
							
							logWarn('no handshake from',addr)
							selfref().skt.close()
							return

					log('connected to',addr)
					#tell torrent I've connected
					keepAliveTimer = repeatTimer(120,selfref().keepAlive)
					def checkIfInteresting(idx):
						if not selfref().torrent().pieceAvailable[idx]:
							selfref().interesting = True
							selfref().interestingBlocks.add(idx)

					while True:
						data = get(4)
						if len(data) < 4:
							raise socket.error() 
						pktLen = struct.unpack('>I',data)[0]

						if pktLen == 0: #keepAlive
							logInfo('keepAlive from',addr)
							continue

						pktType = ord(get(1))
						if pktType == 0: #choke
							selfref().choking = True
							logInfo(addr,'choke')

						elif pktType == 1: #unchoke
							selfref().choking = False
							mainLoop.do(selfref().torrent().unchoke, [selfref()])
							logInfo(addr,'unchoke')

						elif pktType == 2: #interested
							selfref().interested = True
							log(addr,'interested')

						elif pktType == 3: #uninterested
							selfref().interested = False
							log(addr,'uninterested')

						elif pktType == 4: #have
							idx = struct.unpack('>I', get(4))[0]
							selfref().pieceAvailable[idx] = True
							# logInfo(addr,'has',idx)
							checkIfInteresting(idx)

						elif pktType == 5: #bitfield
							selfref().pieceAvailable.set(get(pktLen-1))
							logInfo(addr,'bitfield',selfref().pieceAvailable)
							for idx in range(selfref().torrent().pieceCount):
								checkIfInteresting(idx)

						elif pktType == 6: #request
							(idx, pPos, pLen) = struct.unpack('>III', get(12))
							log(addr,'request',idx,pPos,pLen)
							# if not self.choked and selfref().torrent().pieceAvailable[idx]:
								# self.piece()

						elif pktType == 7: #piece
							# print addr,'piece'
							(idx, pos) = struct.unpack('>II', get(8))
							data = get(pktLen - 9)
							# logInfo(addr,'piece',idx,'[',pos,',',pos+len(data),']')
							selfref().pieceDownloaded(idx, pos, data)

						elif pktType == 8: #cancel
							logWarn(addr,'cancel, ignoring')
							(idx, pPos, pLen) = struct.unpack('>III', get(12))

						elif pktType == 9: #port
							logWarn(addr,'port, ignoring')
							port = struct.unpack('>H', get(2))

						else:
							get(pktLen-1)
							logErr('unknown packet',pktType)
				except socket.error, e:
					logErr('socket error')
				except Exception, e:
					if selfref():
						# traceback.print_exc()
						logErr('shutting down read queue',addr)
				keepAliveTimer.cancel()

			selfref().readThread = threading.Thread(target=recv,name='%s read'%selfref().ip)
			selfref().readThread.start()

			try:
				while True:
					data = selfref().writeQueue.get()
					# print len(data),repr(data)
					selfref().skt.send(data)
					selfref().writeQueue.task_done()
			except socket.error, e:
				logErr('socket error')
			except Exception, e:
				if selfref():
					# traceback.print_exc()
					logErr('shutting down write queue',addr)
			finally:
				#tell torrent I've disconnected
				mainLoop.do(selfref().torrent().disconnection, [(selfref().ip, selfref().port)])
		except:
			pass


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
		logInfo('keepAlive',self.ip, self.port)
		self.sendMessage()

	def pieceDownloaded(self, idx, pos, data):
		# print 'piece downloaded', idx,'pos', pos, 'downloaded',len(self.partialBlockData)

		self.partialBlockData += bytearray(data)
		start, length = self.torrent().blockRange(idx)
		if len(self.partialBlockData) < length:
			self.request(idx, len(self.partialBlockData))
		else : #completely downloaded
			self.downloadingBlock = None
			mainLoop.do(self.torrent().pieceDownloaded, [self, idx, self.partialBlockData])

	def downloadBlock(self,idx):
		self.downloadingBlock = idx
		self.partialBlockData = bytearray()
		pos = len(self.partialBlockData)
		self.request(idx,0)
		# print 'getting piece',idx

	def gotPiece(self,idx):
		if idx in self.interestingBlocks:
			self.interestingBlocks.remove(idx)
			if len(self.interestingBlocks) == 0:
				self.interesting = False
			self.have(idx)


	@property
	def choked(self): return self._choked

	@choked.setter
	def choked(self, value):
		if self._choked == value: return
		self._choked = value
		if self._choked:
			self.sendMessage(0)
		else: self.sendMessage(1)

	@property
	def interesting(self): return self._interesting

	@interesting.setter
	def interesting(self, value):
		if self._interesting == value: return
		self._interesting = value
		if self._interesting:
			self.sendMessage(2)
		else: self.sendMessage(3)

	def have(self,index):
		self.sendMessage(4, struct.pack('>I',index))
	def bitfield(self):
		self.sendMessage(5, self.torrent().pieceAvailable.bytes)
	def request(self,blk,offset):
		self.sendMessage(6, struct.pack('>III',blk,offset,min(1<<14, self.torrent().blockRange(blk)[1] - offset))) # use block size of 2^14
	def piece(self,blk,offset,data):
		self.sendMessage(7, struct.pack('>II',blk,offset) + data)
	def cancel(self,blk,offset):
		self.sendMessage(8, struct.pack('>III',blk,offset,min(1<<14, self.torrent().blockRange(blk)[1] - offset))) # use block size of 2^14

class torrenter:
	firstPort = 6880
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
		for port in range(torrenter.firstPort, torrenter.lastPort+1):
			try:
				self.serverSkt.bind(('', port))
				self.port = port
				log('started on',self.port)
				break
			except Exception, e:
				if port == torrenter.lastPort:
					logErr(e)
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
		self.pieceAvailable = pieceBitfield(self.pieceCount) #RELOAD
		self.pieceDownloading = pieceBitfield(self.pieceCount)

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
			self.info['files'] = [{'path':[self.info['name']], 'length':self.length}]
			self.fileLen.append(self.length)
			self.folder = None

	def downloadRandomBlock(self,peer):
		blk = random.choice(list(peer.interestingBlocks))
		# logInfo('downloading',blk)
		peer.downloadBlock(blk)
		blkUpdate(blk,4)

	def unchoke(self,peer):
		self.downloadRandomBlock(peer)

	def pieceDownloaded(self,peer,blk, data):
		if not self.pieceAvailable[blk]:
			if bytearray(hashlib.sha1(data).digest()) != bytearray(self.pieceHash[blk]):
				logErr('block %5d hash mismatch' % blk)
				blkUpdate(blk,3)
			else:
				self.writeBlock(blk,data)
				self.pieceAvailable[blk] = True
				for p in self.peers.values():
					p.gotPiece(blk)
				self.left -= len(data)
				# log('block %5d downloaded - progress: %3.2f%%'%(blk, 100*(1-self.left/float(self.length))))
				blkUpdate(blk)

		if peer.interesting:
			self.downloadRandomBlock(peer)

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
		log('peer trying to connect:',addr,protocol,peer_id)

	def disconnection(self, peer):
		if peer in self.peers:
			logWarn('connection failed',peer)
			del self.peers[peer]

	def trackerRequest(self,event='',setpeerlist=True):
		url = self.torInfo['announce'] + '?' + self.trackerInfo(event=event)
		response = be.bDecode(urllib.urlopen(url).read())
		if 'failure reason' in response:
			logErr('Tracker returned error',repr(response['failure reason']))
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
			# if num > 10:
			# 	break


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

		return (pieceStart, blkLen)

	def pieceCallback(self,(pieceStart,pieceLen),callback,*info):
		"""
		A block spans multiple files, so for block: blkNum
		Calls callback(filename, fileStart, blkStart, sectionLen, *info)
		on each section of the block from the corresponding files
		"""
		blkStart = 0
		blkLen = pieceLen
		pieceEnd = pieceStart + pieceLen

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
			if len(parent) and not os.path.exists(parent):	
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
	if len(sys.argv) == 2:
		t = torrenter()
		tor = torrent(sys.argv[1],t)
		# be.printBencode(tor.torInfo)

		if False: #test reading and writing
			for i in range(9,-1,-1):
				tor.writeBlock(i,str(i) * tor.info['piece length'])
			for i in range(0,10,2):	
				arr = tor.readBlock(i)
				print arr[:10], arr[-10:]

		def runloop(window):
			window.screen.timeout(20)
			tor.start()
			window.setTitle('%s - press [any key] to quit' % tor.info['name'])
			while True:
				try:
					while True:
						color,item = logQueue.get_nowait()
						if isinstance(item,int):
							window.blockDownloaded(item,color)
						else:
							window.statusUpdate(item,color)
				except: pass

				if window.screen.getch() != -1:
					break

			print 'shutting down (%d)'%threading.activeCount()
			tor.stop()

		torrentWindow(tor.pieceCount, runloop)
		del t
	elif len(sys.argv) == 3:
		tor = be.bDecodeFile(open(sys.argv[2],'r'))
		be.printBencode(tor,byteLen=70)
		# with open(sys.argv[2]) as f:
		# 	url = f.read()
		# print torrent.magnetLink(url)
		# print urllib.urlencode({4:torrent.magnetLink(url)['hash']})
	mainLoop.shutdown()
	sys.exit()

