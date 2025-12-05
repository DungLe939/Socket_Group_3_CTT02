class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		
	def nextFrame(self):
		"""Get next frame."""
		data = self.file.read(6) # Get the framelength from the first 5 bits
		if data:
			try:
				framelength = int(data)
				# Read the current frame
				data = self.file.read(framelength)
				self.frameNum += 1
			except ValueError:
				print("Loi doc Header: Khong phai so nguyen. File co the bi hong hoac sai dinh dang")	
				data = None

		return data
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	def calNumFrames(self):
		"""Calculates total number of frames in the video file."""
		temp_file = open(self.filename, 'rb')
		count = 0
		while True:
			try:
				# Read frame length (assumes 5 bytes length header as per standard assignments)
				data = temp_file.read(6)
				if not data:
					break
				length = int(data)
				# Skip the frame data
				temp_file.seek(length, 1)
				count += 1
			except:
				break
		temp_file.close()
		return count