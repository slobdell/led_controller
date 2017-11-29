VIDEO_INPUT = "vids/amon.mkv"

FRAME_RATE = `cat config.json | jq ".frame_rate"`
FRAME_WIDTH = `cat config.json | jq ".total_screen_width"`
FRAME_HEIGHT = `cat config.json | jq ".total_screen_height"`

column_banner:
	ffmpeg -i vids/output.mp4 -c:v ppm -r $(FRAME_RATE) -f rawvideo - < /dev/null | python pipe_processor.py $(FRAME_RATE)

test:
	# ffmpeg -i $(VIDEO_INPUT) -c:v ppm -r $(FRAME_RATE) -vf "scale=$(FRAME_WIDTH):ih*$(FRAME_WIDTH)/iw, crop=$(FRAME_WIDTH):$(FRAME_HEIGHT)" -f rawvideo - < /dev/null
	ffmpeg -i $(VIDEO_INPUT) -c:v ppm -r $(FRAME_RATE) -vf "scale=$(FRAME_WIDTH):ih*$(FRAME_WIDTH)/iw, crop=$(FRAME_WIDTH):$(FRAME_HEIGHT)" -f rawvideo - < /dev/null | python pipe_processor.py $(FRAME_RATE)

live:
	# ffmpeg -f v4l2 -video_size 320x240 -framerate $(FRAME_RATE) -pixel_format yuyv422 -i /dev/video1 -c:v ppm -r $(FRAME_RATE) -vf "scale=$(FRAME_WIDTH):ih*$(FRAME_WIDTH)/iw, crop=$(FRAME_WIDTH):$(FRAME_HEIGHT)" -f rawvideo -pix_fmt bgr8 - < /dev/null | python pipe_processor.py $(FRAME_RATE)
	ffmpeg -f v4l2 -video_size 320x240 -framerate $(FRAME_RATE) -pixel_format yuyv422 -i /dev/video1 -c:v ppm -r $(FRAME_RATE) -vf "scale=$(FRAME_WIDTH):-1, crop=$(FRAME_WIDTH):$(FRAME_HEIGHT)" -f rawvideo -pix_fmt bgr8 - < /dev/null | python pipe_processor.py $(FRAME_RATE)

# initial res was 720...404
ppm:
	ffmpeg -i $(VIDEO_INPUT) yo%03d.ppm

run:
	gcc read_serial.c; ./a.out

demo:
	open $(VIDEO_INPUT); make test

list:
	ffmpeg -f v4l2 -list_formats all -i /dev/video1

make sample_video:
	ffmpeg -f v4l2 -video_size 320x240 -framerate 25 -pixel_format yuyv422 -i /dev/video1 -vf scale=200:-1 out%03d.jpg
