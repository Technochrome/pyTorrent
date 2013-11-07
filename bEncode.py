import sys
import StringIO

def peek(io):
	p = io.tell()
	c = io.read(1)
	io.seek(p)
	return c

def bDecode(string):
	io = StringIO.StringIO(string)
	def _readInt(io):
		i = 0
		while peek(io).isdigit():
			i = i*10 + ord(io.read(1)) - ord('0')
		return i
	def _decode(io):
		c = peek(io)
		if c == 'd': # dict
			io.read(1)
			ret = {}
			while peek(io) != 'e':
				key = _decode(io)
				value = _decode(io)
				ret[key] = value
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
				ret.append(_decode(io))
			io.read(1) # e
			return ret
		else: # raw data
			dLen = _readInt(io)
			io.read(1) # :
			content = io.read(dLen)
			return content
	return _decode(io)

if __name__ == "__main__":
	if len(sys.argv) == 2:
		with open(sys.argv[1], "r") as myfile:
			d = bDecode(myfile.read())
			for key in d:
				print key
			for key in d['info']:
				print '-',key