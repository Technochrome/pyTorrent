import sys
import StringIO
import string

def peek(io):
	p = io.tell()
	c = io.read(1)
	io.seek(p)
	return c

def bytesToHex(bytes):
	itoch = lambda i: "0123456789ABCDEF"[i]
	return string.join([itoch((c>>4)&0xf) + itoch(c&0xf) for c in bytes],'')

def printBencode(d,tab='',listLen=10,byteLen=40):
	if isinstance(d,dict):
		print tab+'{'
		tab += '\t'
		for key in d:
			if isinstance(d[key],(dict,list,tuple)):
				print tab,key,'='
				printBencode(d[key],tab+'\t',listLen,byteLen)
			else:
				if not key.startswith('__raw_'):
					printBencode(d[key],tab+key+' =',listLen,byteLen)
		print tab[:-1],'}'
	elif isinstance(d,(list,tuple)):
		print tab,'['
		for (i,e) in enumerate(d):
			if i > listLen:
				print tab+'\t...'
				print tab,'\tand %d more' %(len(d)-listLen)
				break
			printBencode(e,tab+'\t')
		print tab,']'
	elif isinstance(d,bytearray):
		bytes = bytesToHex(d)
		if len(bytes)>byteLen:
			print tab,bytes[0:byteLen],'...'
		else:
			print tab,bytes
	elif isinstance(d,basestring):
		if len(d)>byteLen:
			print tab,repr(d[0:byteLen]),'...'
		else:
			print tab,repr(d)
	else:
		print tab,d


def bDecodeFile(io,raw=False):
	def _readInt(io):
		i = 0
		while peek(io).isdigit():
			i = i*10 + ord(io.read(1)) - ord('0')
		return i
	c = peek(io)
	if c == 'd': # dict
		io.read(1)
		ret = {}
		while peek(io) != 'e':
			key = bDecodeFile(io,raw)
			s = io.tell()
			value = bDecodeFile(io,raw)
			ret[key] = value
			e = io.tell()

			#save raw version of entry, necessary for info_hash key
			if raw:
				io.seek(s)
				ret['__raw_'+key] = io.read(e-s)
		io.read(1)
		return ret
	elif c == 'i': # int
		io.read(1)
		i = _readInt(io)
		io.read(1) # e
		return i
	elif c == 'l': # list
		io.read(1)
		ret = []
		while peek(io) != 'e':
			ret.append(bDecodeFile(io,raw))
		io.read(1) # e
		return ret
	else: # raw data
		dLen = _readInt(io)
		io.read(1) # : delimiter
		content = io.read(dLen)
		return content

def bEncode(obj):
	if isinstance(obj,dict):
		ret = 'd'
		for key in obj:
			ret+= bEncode(key)
			ret+= bEncode(obj[key])
		ret+= 'e'
		return ret
	elif isinstance(obj, (list, tuple)):
		ret = 'l'
		for el in obj:
			ret+= bEncode(el)
		ret+= 'e'
		return ret
	elif isinstance(obj, (int, long)):
		return "i%de" % obj
	else:
		s = str(obj)
		return "%d:%s" %(len(s),s)

def bDecode(string,raw=False):
	return bDecodeFile(StringIO.StringIO(string),raw)

if __name__ == "__main__":
	if len(sys.argv) == 2:
		with open(sys.argv[1], "r") as myfile:
			d = bDecode(myfile.read())
			for key in d:
				print key
			for key in d['info']:
				print '-',key