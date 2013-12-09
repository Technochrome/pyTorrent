#!/usr/bin/env python

import threading, Queue, curses, time
import random

def divRem(num, divisor):
	return (num/divisor, num % divisor)

class torrentWindow:
	def doUpdates(self,stdscr,callback):
		self.screen = stdscr
		maxh, maxw = stdscr.getmaxyx()
		progh, progw= 3+(self.blocks-1)/(maxw-2), maxw

		for i in range(1,7):
			curses.init_pair(i,i,curses.COLOR_BLACK)
		curses.init_pair(7,curses.COLOR_WHITE, curses.COLOR_BLACK)

		self.titlebar = stdscr.derwin(1,progw, 0,0)
		self.progressbar = stdscr.derwin(progh, progw, 1, 0)
		self.statusbox = stdscr.derwin(maxh-progh-1, maxw, progh+1, 0)
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
		self.downloaded = 0
		curses.wrapper(self.doUpdates, callback)

	def blockDownloaded(self,blk,color=2):
		(h,w) = self.progressbar.getmaxyx()
		(y,x) = divRem(blk,w-2)
		self.progressbar.addstr(y+1,x+1, ' ', curses.color_pair(color) | curses.A_REVERSE)
		if color==2:
			self.downloaded+=1
			self.progressbar.addstr(h-1,1,' %3.2f%% '%(100*(self.downloaded/float(self.blocks))))
		self.progressbar.move(h-1,w-1)
		self.progressbar.refresh()

	def statusUpdate(self, status, color = 2):
		(h,w) = self.statusbox.getmaxyx()
		self.statusbox.move(0,0)
		# self.statusbox.chgat(0,0,curses.color_pair(0))
		self.statusbox.insertln()
		self.statusbox.insstr(0,0,status, curses.color_pair(color) | curses.A_BOLD)
		self.statusbox.move(h-1,w-1)
		self.statusbox.refresh()

	def setTitle(self, title):
		(h,w) = self.titlebar.getmaxyx()
		self.titlebar.insstr(0,max((w - len(title))/2, 0),title, curses.A_BOLD)

if __name__ == '__main__':
	arr = ['test','930','4','900','status update','901','This is an incredibly long status update (127.0.0.1)'*10,'0','1','2','status update']
	def simulate(t):
		t.screen.timeout(20)
		t.setTitle('example - press [any key] to quit')
		for string in arr:
			if string == 'quit':
				return
			try:
				i = int(string)
				t.blockDownloaded(i)
			except:
				t.statusUpdate(string)
		for blk in range(500):
			t.blockDownloaded(random.randint(100,1300),random.randint(0,7))
			if t.screen.getch() != -1:
				return

	torrentWindow(1340,simulate)
