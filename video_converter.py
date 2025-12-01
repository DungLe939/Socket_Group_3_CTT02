import cv2 
import sys
import os

def convert_to_mjpeg(input_file, output_file, width=960, height=540, quality=90):
    """
    Chuyển đổi video sang định dạng MJPEG custom của dự án.
    Format: [5 bytes length string][jpeg data]
    """
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        return

    cap = cv2.VideoCapture(input_file)
    if not cap.isOpened():
        print(f"Error: Cannot open video file {input_file}")
        return

    print(f"Converting '{input_file}' to '{output_file}'...")
    print(f"Target Resolution: {width}x{height}")
    print(f"JPEG Quality: {quality}")

    with open(output_file, 'wb') as f:
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 1. Resize về HD (hoặc độ phân giải mong muốn)
            frame = cv2.resize(frame, (width, height))
            
            # 2. Nén thành JPEG
            # quality: 0-100 (Càng cao càng nét nhưng dung lượng càng lớn)
            # Cần chỉnh quality sao cho frame size < 60000 bytes để gửi qua UDP an toàn
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            result, encimg = cv2.imencode('.jpg', frame, encode_param)
            
            if result:
                data = encimg.tobytes()
                size = len(data)
                
                # Kiểm tra giới hạn UDP an toàn (~60KB) - Đã có phân mảnh nên không cần lo lắng quá
                # if size > 60000:
                #     print(f"Warning: Frame {frame_count} size {size} bytes is too large for standard UDP! Consider lowering quality.")
                
                # 3. Ghi header 5 bytes (độ dài frame)
                # Ví dụ: size 12345 -> chuỗi "12345"
                f.write(str(size).zfill(5).encode())
                
                # 4. Ghi dữ liệu ảnh
                f.write(data)
                frame_count += 1
                
                if frame_count % 50 == 0:
                    print(f"Processed {frame_count} frames...")

    cap.release()
    print(f"Done! Saved to {output_file}")
    print(f"Total frames: {frame_count}")

if __name__ == "__main__":
    # Ví dụ sử dụng:
    # Bạn có thể thay đổi tên file input ở đây hoặc truyền qua command line
    # python video_converter.py input.mp4 output.Mjpeg
    
    if len(sys.argv) >= 3:
        input_video = sys.argv[1]
        output_video = sys.argv[2]
        convert_to_mjpeg(input_video, output_video)
    else:
        print("Usage: python video_converter.py <input_file> <output_file>")
        print("Example: python video_converter.py myvideo.mp4 movie_hd.Mjpeg")
        
        # Tạo file mẫu nếu không có tham số (để test)
        # convert_to_mjpeg("sample.mp4", "movie_hd.Mjpeg")
