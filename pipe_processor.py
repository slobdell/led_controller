# output form pipe is brg

from collections import deque
from cStringIO import StringIO
import math
import json
import struct
from subprocess import Popen, PIPE
import sys
import time

# requires futures
import concurrent.futures

# requires Pillow==2.7.0
from PIL import Image

# requires numpy
import numpy as np

# requires pyserial
import serial

with open("config.json", "rb") as f:
    config = json.loads(f.read())


MAX_TAILING_SECONDS = 10
frame_rate_maintainer = deque()

MAX_STRIPS_PER_TEENSY = 8
ROWS_PER_STRIP = int(math.ceil(config["total_screen_height"] / MAX_STRIPS_PER_TEENSY))
BYTES_PER_PIXEL = 3
NUM_SHARDS = config["num_shards"]
ALTERNATE_LED_STRIPS = config["alternate_led_strips"]
GLOBAL_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=NUM_SHARDS)
BRIGHTNESS_MULTIPLIER = min(1.0, config.get("brightness_percent", 1.0))
BRG_ORDER = config["brg_order"]

SHOULD_REVERSE_ROWS = config["reverse_rows"]
SHOULD_REVERSE_COLS = config["reverse_cols"]


class Globals(object):
    # should be reassigned at run time
    FRAME_RATE = 25


def get_canonical_device_to_port():
    canonical_name_to_port = {}
    process = Popen(["./find_usb_ports.sh"], stdout=PIPE)
    (output, err) = process.communicate()
    process.wait()
    for line in [line for line in output.split("\n") if line]:
        port, canonical_name = line.split(" - ")
        canonical_name_to_port[canonical_name] = port
    return canonical_name_to_port


def generate_ordered_teensy_ports():
    device_to_port = get_canonical_device_to_port()
    for device, port in sorted(device_to_port.items(), key=lambda pair: pair[0]):
        if "Teensyduino_USB_Serial" in device:
            yield port


# PORT = "/dev/serial/by-id/usb-Teensyduino_USB_Serial_1023950-if00"
# ORDERED_PORTS = list(generate_ordered_teensy_ports())

# mac dev only
ORDERED_PORTS = ["/dev/tty.usbmodem1023951"]

# I don't think baud rate actually matters
BAUD_RATE = 115200

ordered_serial_interfaces = [serial.Serial(port, BAUD_RATE) for port in ORDERED_PORTS]


class PPMState(object):
    READ_P6 = 0
    READ_WIDTH_HEIGHT = 1
    READ_MAX_COLOR = 2
    READ_DATA = 3

    expected_length = sys.maxint


def get_np_array_from_frame(read_buffer, expected_length, (width, height)):
    read_buffer.seek(0)
    return np.array(
        Image.open(
            _image_data_bytes_to_ppm_file(
                read_buffer.read(expected_length),
                (width, height)
            )
        )
    )


def _image_data_bytes_to_ppm_file(image_data, (width, height)):
    ppm_image = StringIO()
    ppm_image.write(
        "P6\n{width} {height}\n255\n".format(
            width=width,
            height=height
        )
    )
    ppm_image.write(image_data)
    ppm_image.seek(0)
    return ppm_image


def generate_np_array_frames_from_std():
    current_state = PPMState.READ_P6
    read_buffer = StringIO()

    for line in sys.stdin:
        if current_state == PPMState.READ_WIDTH_HEIGHT and line.startswith("P6"):
            current_state = PPMState.READ_P6

        if current_state == PPMState.READ_P6:
            current_state = PPMState.READ_WIDTH_HEIGHT

        elif current_state == PPMState.READ_WIDTH_HEIGHT:
            width, height = [int(val) for val in line.split()]
            PPMState.expected_length = width * height * BYTES_PER_PIXEL
            current_state = PPMState.READ_MAX_COLOR

        elif current_state == PPMState.READ_MAX_COLOR:
            # unusued, but this could specify colors > 255
            int(line)  # max color
            current_state = PPMState.READ_DATA

        elif current_state == PPMState.READ_DATA:

            read_buffer.write(line)

            if read_buffer.tell() >= PPMState.expected_length:
                np_array = get_np_array_from_frame(read_buffer, PPMState.expected_length, (width, height))
                read_buffer = StringIO()
                current_state = PPMState.READ_WIDTH_HEIGHT
                yield np_array


CONTROL_SEQUENCE = "".join([chr(255) for _ in range(3)])
META_SEQUENCE = "{control_sequence}{zero_for_framerate}{frame_rate}{zero_for_width}{width_bytes}{zero_for_height}{height_bytes}".format(
    control_sequence=CONTROL_SEQUENCE,
    zero_for_framerate=chr(0),
    frame_rate="%s",
    zero_for_width=chr(0),
    width_bytes="%s",
    zero_for_height=chr(0),
    height_bytes="%s",
)


def _submit_frame_to_serial_interface(serial_interface, sharded_np_array):
    serial_interface.write(
        "%s%s" % (
            _get_frame_meta_bytes(sharded_np_array),
            _get_image_bytes(sharded_np_array),
        )
    )


def _block_for_futures(futures):
    [future.result() for future in futures]


def write_frame_to_buffer(np_array):
    # don't allow 255 in the byte sequence for the control header
    np_array = (np_array * BRIGHTNESS_MULTIPLIER).astype(np.uint8)
    np_array[np_array == 255] = 254

    # swap rgb bits to match LED byte order
    np_array = np_array[:, :, BRG_ORDER]
    _mutate_for_alternating_led_strips(np_array)

    if SHOULD_REVERSE_ROWS:
        np_array = np_array[::-1, :, :]

    if SHOULD_REVERSE_COLS:
        np_array = np_array[:, ::-1, :]

    sleep_to_maintain_framerate()

    futures = []
    for shard_index in xrange(NUM_SHARDS):
        futures.append(
            GLOBAL_THREAD_POOL.submit(
                _submit_frame_to_serial_interface,
                ordered_serial_interfaces[shard_index],
                _sharded_np_array(np_array, shard_index),
            )
        )
    _block_for_futures(futures)


def _mutate_for_alternating_led_strips(np_array):
    """ Difficult to visualize this mentally, but dependong on the set up
    with the octo, we might need to swap the column order on every other teensy
    output (as opposed to alternating what side the wires are stuck into. """
    if not ALTERNATE_LED_STRIPS:
        return

    for strip_offset in range(MAX_STRIPS_PER_TEENSY):
        if strip_offset % 2 == 0:
            continue
        current_row = strip_offset * ROWS_PER_STRIP
        np_array[current_row: current_row + ROWS_PER_STRIP] = np_array[current_row: current_row + ROWS_PER_STRIP, ::-1, :]


def sleep_to_maintain_framerate():
    _discard_old_timestamps()
    time.sleep(_get_sleep_delta())
    frame_rate_maintainer.append(time.time())


def _discard_old_timestamps():
    now_ts = time.time()
    while frame_rate_maintainer and now_ts - frame_rate_maintainer[0] > MAX_TAILING_SECONDS:
        frame_rate_maintainer.popleft()


def _get_sleep_delta():
    desired_frame_rate = 1.0 / Globals.FRAME_RATE
    if not frame_rate_maintainer or len(frame_rate_maintainer) == 1:
        return desired_frame_rate

    delta_t = frame_rate_maintainer[-1] - frame_rate_maintainer[0]
    sleep_for_next_frame = desired_frame_rate * (len(frame_rate_maintainer)) - delta_t  # took out a +1 from this formula after len(fr)

    if sleep_for_next_frame < 0:
        return 0

    if sleep_for_next_frame < desired_frame_rate:
        return desired_frame_rate / 2.0

    return sleep_for_next_frame


def _sharded_np_array(np_array, shard_index):
    num_rows_per_shard = len(np_array) / NUM_SHARDS
    start_row = shard_index * num_rows_per_shard
    end_row = (shard_index + 1) * num_rows_per_shard
    return np_array[start_row: end_row, :]


def _get_image_bytes(np_array):
    return np_array.flatten().tobytes()


def _get_frame_meta_bytes(np_array):
    height, width, depth = np_array.shape
    frame_rate_bytes = struct.pack("H", Globals.FRAME_RATE)
    width_bytes = struct.pack("H", width)
    height_bytes = struct.pack("H", height)
    return META_SEQUENCE % (frame_rate_bytes, width_bytes, height_bytes)


if __name__ == "__main__":
    Globals.FRAME_RATE = int(sys.argv[1])
    try:
        for np_array in generate_np_array_frames_from_std():
            write_frame_to_buffer(np_array)
    finally:
        for serial_interface in ordered_serial_interfaces:
            serial_interface.close()
