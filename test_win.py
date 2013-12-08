#!/usr/bin/env python

import threading, Queue, curses, time
import random

def divRem(num, divisor):
	return (num/divisor, num % divisor)

class torrentWindow:
	def doUpdates(self,stdscr,callback):
		maxh, maxw = stdscr.getmaxyx()
		progh, progw= 3+(self.blocks-1)/(maxw-2), maxw

		for i in range(1,7):
			curses.init_pair(i,i,curses.COLOR_BLACK)
		curses.init_pair(7,curses.COLOR_WHITE, curses.COLOR_BLACK)

		self.progressbar = curses.newwin(progh, progw, 0, 0)
		self.statusbox = curses.newwin(maxh-progh, maxw, progh, 0)
		self.progressbar.border()
		self.progressbar.refresh()
		self.progressbar.leaveok(0)

		remainder = self.blocks%(maxw-2)
		if remainder:
			for i in range(maxw-2-remainder):
				self.blockDownloaded(self.blocks+i,0)
		callback(self)

	def __init__(self,blocks,callback):
		self.blocks = blocks
		curses.wrapper(self.doUpdates, callback)

	def blockDownloaded(self,blk,color=2):
		(h,w) = self.progressbar.getmaxyx()
		(y,x) = divRem(blk,w-2)
		self.progressbar.addstr(y+1,x+1, ' ', curses.color_pair(color) | curses.A_REVERSE)
		self.progressbar.move(0,0)
		self.progressbar.refresh()

	def statusUpdate(self, status, color = 2):
		(h,w) = self.statusbox.getmaxyx()
		self.statusbox.move(0,0)
		self.statusbox.chgat(0,0,curses.color_pair(0))
		self.statusbox.insertln()
		self.statusbox.insstr(0,0,status, curses.color_pair(color) | curses.A_BOLD)
		self.statusbox.refresh()

arr = ['test','930','4','900','status update','901','This is an incredibly long status update (127.0.0.1)'*10,'0','1','2','status update']
def simulate(t):
	for string in arr:
		if string == 'quit':
			return
		try:
			i = int(string)
			t.blockDownloaded(i)
		except:
			t.statusUpdate(string)
		time.sleep(.2)
	for blk in range(500):
		t.blockDownloaded(random.randint(100,1300),random.randint(0,7))
		time.sleep(.2)

torrentWindow(1340,simulate)
