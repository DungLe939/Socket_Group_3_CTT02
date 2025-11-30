# How to run the project
1. Open a terminal and navigate to the project directory
2. Run the server by executing the following command: python ./Server.py <server_port>
3. Run the client by executing the following command: python ./ClientLauncher.py <server_address> <server_port> <rtp_port> <video_file>
- For example: 
python ./Server.py 4000
python ./ClientLauncher.py 127.0.0.1 4000 25000 movie.Mjpeg

