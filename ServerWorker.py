from random import randint
import sys, traceback, threading, socket, os, time

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	clientInfo = {}
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		# Initialize total frames
		self.clientInfo['total_frames'] = 0
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def do_conversion(self, source_path, target_path):
		"""Convert Raw MJPEG->Lab Format"""
		print(f"DEBUG: Converting '{source_path}' -> '{target_path}'...")
		try:
			with open(source_path, 'rb') as f_in:
				data = f_in.read()

			SOI_MARKER = b'\xff\xd8'
			EOI_MARKER = b'\xff\xd9'
			cursor = 0
			total_size = len(data)
			with open(target_path, 'wb') as f_out:
				while cursor < total_size:
					start_pos = data.find(SOI_MARKER, cursor)
					if start_pos == -1:
						break
					end_pos = data.find(EOI_MARKER, start_pos)
					if end_pos == -1:
						break
					end_pos += 2
					frame_data = data[start_pos:end_pos]
					header = str(len(frame_data)).zfill(6).encode()
					f_out.write(header)
					f_out.write(frame_data)
					cursor = end_pos
			print(f"DEBUG: Conversion successful! created {target_path}")
			return target_path

		except Exception as e: 
			print(f"DEBUG: Conversion failed: {e}")
			return None

	def prepare_video_file(self, target_filename, source_filename):
		if os.path.exists(target_filename):
			with open(target_filename, 'rb') as f:
				header = f.read(6)
				if header.isdigit():
					print(f"DEBUG: Found ready-to-use file:  {target_filename}")
					return target_filename
				else:
					return self.do_conversion(target_filename, target_filename)

		if os.path.exists(source_filename):
			print(f"DEBUG: Target {target_filename} missing. Generating from source {source_filename}")
			return self.do_conversion(source_filename, target_filename)

		print(f"ERROR: Neither {target_filename} nor {source_filename} found.")
		return None

	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0]
		while True:            
			data = connSocket.recv(256)
			if data:
				print("Data received:\n" + data.decode("utf-8"))
				self.processRtspRequest(data.decode("utf-8"))
	
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Example:
		# C: SETUP movie.Mjpeg RTSP/1.0 
		# C: CSeq: 1 
		# C: Transport: RTP/UDP; client_port=25000

		# Get the request type and fileName
		request = data.split('\n')
		line1 = request[0].split(' ')

		requestType = line1[0]
		filename = line1[1]
		
		# Get the RTSP sequence number 
		seq = request[1].split(' ')
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				# Update state
				print("processing SETUP\n")

				target_filename = filename
				for line in request:
					if "X-Quality: " in line:
						quality = line.split(":")[1].strip()
						print(f"DEBUG: Client requested Quality:  {quality}")

						if quality == "HD":
							if "." in filename:
								name_part, ext_part = filename.rsplit('.', 1)
								target_filename = f"{name_part}_hd.{ext_part}"
							else:
								target_filename = filename + "_hd"
				print(f"DEBUG: Opening file -> {target_filename}")

				#Auto convert
				ready_file = self.prepare_video_file(target_filename, filename)

				if ready_file:
					try:
						self.clientInfo['videoStream'] = VideoStream(ready_file)
						# # Calculate total frames
						self.clientInfo['total_frames'] = self.clientInfo['videoStream'].calNumFrames()
						self.state = self.READY
					except IOError:
						self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				else:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
					return
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1])
				
				# Get the RTP/UDP port from the last line
				self.clientInfo['rtpPort'] = request[2].split('client_port=')[1]

				self.clientInfo['rtpAddr'] = self.clientInfo['rtspSocket'][1][0]
				self.clientInfo['fps_interval'] = 0.05 #20 fps
				for line in request:
					if "Frame-Rate:" in line:
						try:
							fps_val = int(line.split(":")[1].strip())
							if fps_val > 0:
								self.clientInfo['fps_interval'] = 1.0 / fps_val
								print(f"DEBUG: Set FPS to {fps_val} (Internal: {self.clientInfo['fps_interval']})")
						except:
							print("DEBUG: Error parsing Frame-Rate header")
		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING
				
				# Create a new socket for RTP/UDP
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				self.clientInfo['rtpPacket'] = RtpPacket()
				
				self.replyRtsp(self.OK_200, seq[1])
				
				# Create a new thread and start sending RTP packets
				self.clientInfo['event'] = threading.Event()
				self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				# Only stop event if it exists
				if 'event' in self.clientInfo:
					self.clientInfo['event'].set()
			
				self.replyRtsp(self.OK_200, seq[1])
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			if 'event' in self.clientInfo:
				self.clientInfo['event'].set()
			
			self.replyRtsp(self.OK_200, seq[1])
			
			# Close the RTP socket
			if 'rtpSocket' in self.clientInfo:
				self.clientInfo['rtpSocket'].close()
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			# Can make feature speed control (FPS, Frame per second)
			if 'fps_interval' in self.clientInfo:
				wait_time = self.clientInfo['fps_interval']
			else:
				wait_time = 0.05
			self.clientInfo['event'].wait(wait_time) 
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet(): 
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				try:
					# address = self.clientInfo['rtspSocket'][1][0]
					address = self.clientInfo['rtpAddr']
					port = int(self.clientInfo['rtpPort'])
					# self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber, 1),(address,port))

					MAX_PAYLOAD = 1400
					data_len = len(data)
					start_pos = 0

					while start_pos < data_len:
						end_pos = min(start_pos + MAX_PAYLOAD, data_len)

						payload_chunk = data[start_pos:end_pos]
						if end_pos == data_len:
							marker = 1
						else:
							marker = 0

						self.clientInfo['rtpPacket'].encode(
							version=2, padding=0, extension=0, cc=0,
							seqnum=frameNumber,
							marker=marker, 
							pt=26,ssrc=0,
							payload=payload_chunk
						)
						self.clientInfo['rtpSocket'].sendto(self.clientInfo['rtpPacket'].getPacket(), (address, port))
						time.sleep(0.0001)
						start_pos = end_pos

				except Exception as e:
					print("Connection Error", e)
					traceback.print_exc()

					#print('-'*60)
					#traceback.print_exc(file=sys.stdout)
					#print('-'*60)

	def makeRtp(self, payload, frameNbr, marker):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		pt = 26 # MJPEG type
		seqnum = frameNbr
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#print("200 OK")
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])

			# Send the total frames in the header if available
			if self.clientInfo['total_frames'] > 0:
				reply += '\nTotal-Frames: ' + str(self.clientInfo['total_frames'])

			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")