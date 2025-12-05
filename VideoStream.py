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
		data = self.file.read(6) # Get the framelength from the first 6 bits
		if data: 
			try:
				framelength = int(data)
				#Read the current frame
				data = self.file.read(framelength)
				self.frameNum += 1
			except ValueError:
				print("Loi doc Header: Khong phai so nguyen. File co the bi hong hoac sai dinh dang")	
				data = None
		return data
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	