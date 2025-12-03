from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os
import tkinter.ttk as ttk


from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	# Initiation..
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)
		self.createWidgets()
		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename

		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		self.frameNbr = -1

		self.connectToServer()

		self.framebuffer = []
		self.highest_received_frame = 0

		self.BUFFER_CAP = 100 # Cache limit so server stop downloading after 100 frames
		self.rtp_thread = None # Track the thread so we don't start duplicates
		
	def createWidgets(self):
		"""Build GUI."""
		# Create Setup button
		self.setup = Button(self.master, width=20, padx=3, pady=3)
		self.setup["text"] = "Setup"
		self.setup["command"] = self.setupMovie
		self.setup.grid(row=3, column=0, padx=2, pady=2)
		
		# Create Play button		
		self.start = Button(self.master, width=20, padx=3, pady=3)
		self.start["text"] = "Play"
		self.start["command"] = self.playMovie
		self.start.grid(row=3, column=1, padx=2, pady=2)
		
		# Create Pause button			
		self.pause = Button(self.master, width=20, padx=3, pady=3)
		self.pause["text"] = "Pause"
		self.pause["command"] = self.pauseMovie
		self.pause.grid(row=3, column=2, padx=2, pady=2)
		
		# Create Teardown button
		self.teardown = Button(self.master, width=20, padx=3, pady=3)
		self.teardown["text"] = "Teardown"
		self.teardown["command"] =  self.exitClient
		self.teardown.grid(row=3, column=3, padx=2, pady=2)
		
		# Create a label to display the movie
		self.label = Label(self.master, height=19)
		self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 

		# Cache Bar
		self.buffer_bar = ttk.Progressbar(self.master, orient = HORIZONTAL, length = 400, mode = 'determinate')
		self.buffer_bar.grid(row = 1, column = 0, columnspan = 4, sticky = W + E, padx = 10, pady = (10, 0))
		self.buffer_bar["maximum"] = 500 # Video frames length
	
		# Progress Bar
		self.progress_slider = Scale(self.master, from_ = 0, to = 500, orient = HORIZONTAL, showvalue = 0, width = 10, troughcolor = 'white', activebackground = 'red', bd = 0)
		self.progress_slider.grid(row = 2, column = 0, columnspan = 4, sticky = W + E, padx = 10)

	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN)		
		self.master.destroy() # Close the gui window
		os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.state = self.READY
			# Don't send stop request, let server sending data for cache
			# self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:

			# Only start listening thread if it's not running
			if self.rtp_thread is None or not self.rtp_thread.is_alive():
				self.rtp_thread = threading.Thread(target = self.listenRtp)
				self.rtp_thread.start()

			# Check if we need to wake up the paused server because of buffer limit
			if self.requestSent == self.PAUSE:
				self.playEvent = threading.Event()
				self.playEvent.clear()
				self.sendRtspRequest(self.PLAY)

			# Resume playing
			self.state = self.PLAYING
			self.updateMovie()

			# Check if this is the first time
			if self.requestSent == self.SETUP:
				self.playEvent = threading.Event()
				self.playEvent.clear()
				self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self):		
		"""Listen for RTP packets."""
		while True:
			try:
				curr_buffer = len(self.framebuffer)

				# Check if buffer passes the limit (100), if so pause buffering
				if curr_buffer >= self.BUFFER_CAP:
					if self.requestSent != self.PAUSE:
						self.sendRtspRequest(self.PAUSE)

				# Check if buffer is below the minimum (80), if so play buffering
				elif curr_buffer < (self.BUFFER_CAP - 20):
					if self.requestSent == self.PAUSE:
						self.sendRtspRequest(self.PLAY)

				# Receive data
				data, addr = self.rtpSocket.recvfrom(20480)
				if data:
					rtpPacket = RtpPacket()
					rtpPacket.decode(data)
					
					currFrameNbr = rtpPacket.seqNum()
					print("Current Seq Num: " + str(currFrameNbr))

					# Check if the current frame is bigger than the received frame
					if currFrameNbr > self.highest_received_frame:
						self.highest_received_frame = currFrameNbr
						self.buffer_bar["value"] = self.highest_received_frame

					if currFrameNbr > self.frameNbr: # Discard the late packet
						self.frameNbr = currFrameNbr
						self.framebuffer.append((currFrameNbr, rtpPacket.getPayload()))

			except socket.timeout:
				# If server stopped sending because we sent pause, socket will timeout
				# but keep the loop to keep the thread alive
				if self.teardownAcked == 1:
					break
				continue

			except Exception as e:
				print(traceback.format_exc())

				# Stop listening upon requesting PAUSE or TEARDOWN
				if self.playEvent.isSet(): 
					break
				
				# Upon receiving ACK for TEARDOWN request,
				# close the RTP socket
				if self.teardownAcked == 1:
					self.rtpSocket.shutdown(socket.SHUT_RDWR)
					self.rtpSocket.close()
					break
					
	def writeFrame(self, data):
		"""Write the received frame to a temp image file. Return the image file."""
		cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		file = open(cachename, "wb")
		file.write(data)
		file.close()
		
		return cachename

	def updateMovie(self):
		"""Update the image file as video frame in the GUI"""
		if self.state == self.PLAYING:
			# Update the buffer slider
			if len(self.framebuffer) > 0:
				frame_number, image_data = self.framebuffer.pop(0)
				self.progress_slider.set(frame_number)

				file_name = CACHE_FILE_NAME + str(self.sessionId) +CACHE_FILE_EXT
				with open(file_name, "wb") as file:
					file.write(image_data)
				
				try:
					photo = ImageTk.PhotoImage(Image.open(file_name))
					self.label.configure(image = photo, height = 288)
					self.label.image = photo
				except:
					print("Bad frame")

			self.master.after(50, self.updateMovie)

	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			tkinter.messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server."""	
		#-------------
		# TO COMPLETE
		#-------------
		
		# Setup request
		if requestCode == self.SETUP and self.state == self.INIT:
			threading.Thread(target=self.recvRtspReply).start()
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			# For example:
			# C: SETUP movie.Mjpeg RTSP/1.0 
			# C: CSeq: 1 
			# C: Transport: RTP/UDP; client_port=25000
			request = "SETUP " + str(self.fileName) + " RTSP/1.0\n"
			request += "CSeq: " + str(self.rtspSeq) + "\n"
			request += "Transport: RTP/UDP;" + " client_port=" + str(self.rtpPort)
			# Keep track of the sent request.
			self.requestSent = self.SETUP
		
		# Play request
		elif requestCode == self.PLAY:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			# For example
			# C: PLAY movie.Mjpeg RTSP/1.0 
			# C: CSeq: 2 
			# C: Session: 123456 
			request = "PLAY " + self.fileName + " RTSP/1.0\n"
			request += "CSeq: " + str(self.rtspSeq) + "\n"
			request += "Session: " + str(self.sessionId)
			# Keep track of the sent request.
			self.requestSent = self.PLAY
		
		# Pause request
		elif requestCode == self.PAUSE:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			# For example
			# C: PLAY movie.Mjpeg RTSP/1.0 
			# C: CSeq: 2 
			# C: Session: 123456 
			request = "PAUSE " + self.fileName + " RTSP/1.0\n"
			request += "CSeq: " + str(self.rtspSeq) + "\n"
			request += "Session: " + str(self.sessionId)
			# Keep track of the sent request.
			self.requestSent = self.PAUSE
			
		# Teardown request
		elif requestCode == self.TEARDOWN and not self.state == self.INIT:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			# For example
			# C: TEARDOWN movie.Mjpeg RTSP/1.0 
			# C: CSeq: 2 
			# C: Session: 123456 
			request = "TEARDOWN " + self.fileName + " RTSP/1.0\n"
			request += "CSeq: " + str(self.rtspSeq) + "\n"
			request += "Session: " + str(self.sessionId)
			# Keep track of the sent request.
			self.requestSent = self.TEARDOWN
		else:
			return
		
		# Send the RTSP request using rtspSocket.
		self.rtspSocket.send(request.encode("utf-8"))
		
		print('\nData sent:\n' + request)
	
	def recvRtspReply(self):
		"""Receive RTSP reply from the server."""
		while True:
			reply = self.rtspSocket.recv(1024) 
			
			if reply: 
				self.parseRtspReply(reply.decode("utf-8"))
			
			# Close the RTSP socket upon requesting Teardown
			if self.requestSent == self.TEARDOWN:
				self.rtspSocket.shutdown(socket.SHUT_RDWR)
				self.rtspSocket.close()
				break
	
	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		print("DEBUG: Received Reply from Server:\n" + data)

		try:
			lines = data.split('\n')
			seqNum = int(lines[1].split(' ')[1])
			
			# Process only if the server reply's sequence number is the same as the request's
			if seqNum == self.rtspSeq:
				session = int(lines[2].split(' ')[1])
				# New RTSP session ID
				if self.sessionId == 0:
					self.sessionId = session
				
				# Process only if the session ID is the same
				if self.sessionId == session:
					if int(lines[0].split(' ')[1]) == 200: 
						if self.requestSent == self.SETUP:
							#-------------
							# TO COMPLETE
							#-------------
							# Update RTSP state.
							self.state = self.READY
							
							# Open RTP port.
							self.openRtpPort() 
						elif self.requestSent == self.PLAY:
							pass
						elif self.requestSent == self.PAUSE:
							# # The play thread exits. A new thread is created on resume.
							self.playEvent.set()
							pass
						elif self.requestSent == self.TEARDOWN:
							self.state = self.INIT
							
							# Flag the teardownAcked to close the socket.
							self.teardownAcked = 1
		except:
			traceback.print_exc()

	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""
		#-------------
		# TO COMPLETE
		#-------------
		# Create a new datagram socket to receive RTP packets from the server
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		
		# Set the timeout value of the socket to 0.5sec
		self.rtpSocket.settimeout(0.5)
		
		try:
			# Bind the socket to the address using the RTP port given by the client user
			self.rtpSocket.bind(("", self.rtpPort))
		except:
			tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: # When the user presses cancel, resume playing.
			self.playMovie()
