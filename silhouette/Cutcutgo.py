# Driver for Cricut Maker 1 devices running CutcutGo
# 
# Roadmap
# -------
#
# [ ] Automatic detection of CutcutGo firmware 

import os
import re
import sys
import time
from serial import Serial, SerialException
from serial.tools import list_ports

sys_platform = sys.platform.lower()

MEDIA = [
# CAUTION: keep in sync with sendto_silhouette.inx
# media, pressure, speed, depth, cap-color, name
  ( 100,   27,     10,   1,  "yellow", "Card without Craft Paper Backing"),
  ( 101,   27,     10,   1,  "yellow", "Card with Craft Paper Backing"),
  ( 102,   10,      5,   1,  "blue",   "Vinyl Sticker"),
  ( 106,   14,     10,   1,  "blue",   "Film Labels"),
  ( 111,   27,     10,   1,  "yellow", "Thick Media"),
  ( 112,    2,     10,   1,  "blue",   "Thin Media"),
  ( 113,   18,     10,None,  "pen",    "Pen"),
  ( 120,   30,     10,   1,  "blue",   "Bond Paper 13-28 lbs (105g)"),
  ( 121,   30,     10,   1,  "yellow", "Bristol Paper 57-67 lbs (145g)"),
  ( 122,   30,     10,   1,  "yellow", "Cardstock 40-60 lbs (90g)"),
  ( 123,   30,     10,   1,  "yellow", "Cover 40-60 lbs (170g)"),
  ( 124,    1,     10,   1,  "blue",   "Film, Double Matte Translucent"),
  ( 125,    1,     10,   1,  "blue",   "Film, Vinyl With Adhesive Back"),
  ( 126,    1,     10,   1,  "blue",   "Film, Window With Kling Adhesive"),
  ( 127,   30,     10,   1,  "red",    "Index 90 lbs (165g)"),
  ( 128,   20,     10,   1,  "yellow", "Inkjet Photo Paper 28-44 lbs (70g)"),
  ( 129,   27,     10,   1,  "red",    "Inkjet Photo Paper 45-75 lbs (110g)"),
  ( 130,   30,      3,   1,  "red",    "Magnetic Sheet"),
  ( 131,   30,     10,   1,  "blue",   "Offset 24-60 lbs (90g)"),
  ( 132,    5,     10,   1,  "blue",   "Print Paper Light Weight"),
  ( 133,   25,     10,   1,  "yellow", "Print Paper Medium Weight"),
  ( 134,   20,     10,   1,  "blue",   "Sticker Sheet"),
  ( 135,   20,     10,   1,  "red",    "Tag 100 lbs (275g)"),
  ( 136,   30,     10,   1,  "blue",   "Text Paper 24-70 lbs (105g)"),
  ( 137,   30,     10,   1,  "yellow", "Vellum Bristol 57-67 lbs (145g)"),
  ( 138,   30,     10,   1,  "blue",   "Writing Paper 24-70 lbs (105g)"),
  ( 300, None,   None,None,  "custom", "Custom"),
]

CRICUT_MATS = dict(
  no_mat=('0', False, False),
  cameo_12x12=('1', 12, 12),
  cameo_12x24=('2', 24, 12),
  portrait_8x12=('3', 12, 8),
  cameo_plus_15x15=('8', 15, 15),
  cameo_pro_24x24=('9', 24, 24)
)

VENDOR_ID_CRICUT = 0x04d8
PRODUCT_ID_CRICUT_MAKER1 = 0x000a

DEVICE = [
 # CAUTION: keep in sync with sendto_silhouette.inx
 { 'vendor_id': VENDOR_ID_CRICUT, 'product_id': PRODUCT_ID_CRICUT_MAKER1, 'name': 'Cricut_Maker1',
   'width_mm':  206, 'length_mm': 3000, 'regmark': True },
]


def _bbox_extend(bb, x, y):
    # The coordinate system origin is in the top lefthand corner.
    # Downwards and rightwards we count positive. Just like SVG or HPGL.
    # Thus lly is a higher number than ury
    if not 'llx' in bb or x < bb['llx']: bb['llx'] = x
    if not 'urx' in bb or x > bb['urx']: bb['urx'] = x
    if not 'lly' in bb or y > bb['lly']: bb['lly'] = y
    if not 'ury' in bb or y < bb['ury']: bb['ury'] = y

def to_bytes(b_or_s):
  """Ensure a value is bytes"""
  if isinstance(b_or_s, str): return b_or_s.encode()
  if isinstance(b_or_s, bytes): return b_or_s
  raise TypeError("Value must be a string or bytes.")

class CricutMaker:
  def __init__(self, log=sys.stderr, cmdfile=None, inc_queries=False,
               dry_run=False, progress_cb=None, force_hardware=None):
    """ This initializer simply finds the first known device.
        The default paper alignment is left hand side for devices with known width
        (currently Cameo and Portrait). Otherwise it is right hand side.
        Use setup() to specify your needs.

        If cmdfile is specified, it is taken as a file-like object in which to
        record a transcript of all commands sent to the cutter. If inc_queries is
        True, then that transcript further includes all of the queries sent to
        the cutter (but not the responses read back). (The latter parameter
        inc_queries has no effect when cmdfile is unspecified or falsy.)

        If dry_run is True, no commands will be sent to the usb device. The device
        is still searched for and queries to it are allowed, as the responses
        might affect inkscape_silhouette's behavior during the dry run. (Note that
        we might be dumping information from the run for later use that depends
        on what device is being driven.) Of course, when dry_run is True, it is
        allowed that there be no device currently attached.

        The progress_cb is called with the following parameters:
        int(strokes_done), int(strikes_total), str(status_flags)
        The status_flags contain 't' when there was a (non-fatal) write timeout
        on the device.
    """
    self.leftaligned = False            # True: only works for DEVICE with known hardware.width_mm
    self.log = log
    self.commands = cmdfile
    self.inc_queries = inc_queries
    self.dry_run = dry_run
    self.progress_cb = progress_cb
    dev = None
    self.margins_printed = None

    if self.dry_run:
      print("Dry run specified; no commands will be sent to cutter.",
            file=self.log)

    dev = None

    # Enumerate com ports (serial ports)
    ports = list(list_ports.comports())
    for port in ports:
      # Extract VID/PID from hardware info (should work on Linux and Windows)
      vid_pid = re.search('VID:PID=([a-fA-F0-9]{4}):([a-fA-F0-9]{4})', port.usb_info())
      if vid_pid is not None:
        vid, pid = map(lambda x: int(x, 16), vid_pid.groups())

        # If VID/PID matches a device, then we got it ! 
        for hardware in DEVICE:
          if hardware['vendor_id'] == vid and hardware['product_id'] == pid:
            self.hardware = hardware
            # TODO: handle potential exceptions.
            dev = Serial(port.device, baudrate=115200, timeout=5000)
            dev_port = port.device
        
        # If our Cricut device has been found, exit search
        if dev is not None:
          break

    # If no device has been found
    if dev is None:
        # If dry run enabled, continue
        if dry_run:
            print("No device detected; continuing dry run with dummy device",
                file=self.log)
            self.hardware = dict(name='Crashtest Dummy Device')
        else:
            # Raise an error if no Cricut device found.
            raise ValueError('No Cricut Maker devices found.\nCheck USB and Power.')
        
    print("%s found on port %s" % (self.hardware['name'], dev_port), file=self.log)

    self.dev = dev
    self.need_interface = False         # probably never needed, but harmful on some versions of usb.core
    self.regmark = False                # not yet implemented. See robocut/Plotter.cpp:446
    if self.dev is None or 'width_mm' in self.hardware:
      self.leftaligned = True
    self.enable_sw_clipping = True
    self.clip_fuzz = 0.05
    self.mock_response = None
    self.tool_up = True

  def __del__(self, *args):
    if self.commands:
      self.commands.close()

  def product_id(self):
    return self.hardware['product_id'] if 'product_id' in self.hardware else None


  #############################
  # Device IO methods
  #############################

  def read(self, size=64, timeout=5000):
    """TODO: implement serial read line
    """
    self.dev.timeout = timeout
    try:
      return self.dev.readline()
    except SerialException as err:
      raise ValueError('read failed: none')

  def write(self, data, is_query=False, timeout=10000):
    """Send a command to the device. Long commands are sent in chunks of 4096 bytes.
       A nonblocking read() is attempted before write(), to find spurious diagnostics.
    """
    self.dev.write_timeout = timeout
    self.dev.write(data)

  def safe_write(self, data):
    """
        Wrapper for write with special emphasis not overloading the cutter
        with long commands.
        Use this only for commands, not queries.

        Actually a simple wrapper for write() =]
    """
    return self.write(data)

  def send_command(self, cmd, is_query = False, timeout=10000):
    """ Sends a command or a list of commands """
    self.write(cmd+b'\n', is_query=is_query, timeout=timeout)

  def send_special_command(self, cmd, timeout=10000):
    """Send GRBL special command like '?'
    """
    self.write(cmd, is_query=False, timeout=timeout)

  def try_read(self, size=64, timeout=1000):
    ret=None
    try:
      ret = self.read(size=size,timeout=timeout)
      print("try_read got: '%s'" % ret)
    except:
      pass
    return ret

  def send_receive_command(self, cmds, tx_timeout=10000, rx_timeout=20000, special=False):
    if not isinstance(cmds, list):
      if special:
        return '<Idle24835|MPos:0.000,0.000,0.000|F:0|Pn:P>'
        self.send_special_command(cmd, timeout=tx_timeout)
        try:
          resp = self.read(timeout=rx_timeout)
          if len(resp) > 1:
            return resp[:-1].decode()
        except:
          pass
      else:
        cmds = [cmds]

    msg = ''
    o = 0
    for cmd in cmds:
      """ Sends a query and returns its response as a string """
      if special:
        self.send_special_command(cmd, timeout=tx_timeout)
      else:
        self.send_command(cmd, is_query=True, timeout=tx_timeout)

      try:
        resp = self.read(timeout=rx_timeout)
      except:
        msg += 't'
        pass
      else:
        msg = ''
        self.log.write("\n")
      
      if self.progress_cb:
          self.progress_cb(o,len(cmds), msg)
      elif self.log:
        self.log.write(" %d%% %s\r" % (100.*o/len(cmds),msg))
        self.log.flush()

    return None

  #############################
  # Info getters
  #############################

  def status(self):
    """Query the device status. This can return one of the three strings
       'ready', 'moving', 'unloaded' or a raw (unknown) byte sequence.

      TODO: implement this feature   
    """
    return 'ready'
   

  #############################
  # Commands
  #############################

  def acceleration_cmd(self, acceleration):
    """ Not supported yet """
    return ""

  def move_mm_cmd(self, mmy, mmx):
    """ Raise tool and move """
    if self.tool_up:
      return [b"G01X%fY%fF10" % (mmx, mmy)]
    else:
      self.tool_up = True
      return [b"G01Z0F10", b"G01X%fY%fF10" % (mmx, mmy)]

  def draw_mm_cmd(self, mmy, mmx):
    """ Lower tool (if not lowered) and cut """
    if self.tool_up:
      self.tool_up = False 
      return [b"G01Z-10F10", b"G01X%fY%fF10" % (mmx, mmy)]
    else:
      return [b"G01X%fY%fF10" % (mmx, mmy)]

  def upper_left_mm_cmd(self, mmy, mmx):
    """" Not supported yet """
    return []

  def lower_right_mm_cmd(self, mmy, mmx):
    """" Not supported yet """
    return []

  def automatic_regmark_test_mm_cmd(self, height, width, top, left):
    """" Not supported yet """
    return []
  
  def manual_regmark_mm_cmd(self, height, width):
    """" Not supported yet """
    return []
  

  def clip_point(self, x, y, bbox):
    """
        Clips coords x and y by the 'clip' element of bbox.
        Returns the clipped x, clipped y, and a flag which is true if
        no actual clipping took place.
    """
    inside = True
    if 'clip' not in bbox:
      return x, y, inside
    if 'count' not in bbox['clip']:
      bbox['clip']['count'] = 0
    if bbox['clip']['llx'] - x > self.clip_fuzz:
      x = bbox['clip']['llx']
      inside = False
    if x - bbox['clip']['urx'] > self.clip_fuzz:
      x = bbox['clip']['urx']
      inside = False
    if bbox['clip']['ury'] - y > self.clip_fuzz:
      y = bbox['clip']['ury']
      inside = False
    if y - bbox['clip']['lly'] > self.clip_fuzz:
      y = bbox['clip']['lly']
      inside = False
    if not inside:
      #print(f"Clipped point ({x},{y})", file=self.log)
      bbox['clip']['count'] += 1
    return x, y, inside
  
  def plot_cmds(self, plist, bbox, x_off, y_off):
    """
        bbox coordinates are in mm
        bbox *should* contain a proper { 'clip': {'llx': , 'lly': , 'urx': , 'ury': } }
        otherwise a hardcoded flip width is used to make the coordinate system left aligned.
        x_off, y_off are in mm, relative to the clip urx, ury.
    """

    # Change by Alexander Senger:
    # Well, there seems to be a clash of different coordinate systems here:
    # Cameo uses a system with the origin in the top-left corner, x-axis
    # running from top to bottom and y-axis from left to right.
    # Inkscape uses a system where the origin is also in the top-left corner
    # but x-axis is running from left to right and y-axis from top to
    # bottom.
    # The transform between these two systems used so far was to set Cameo in
    # landscape-mode ("FN0.TB50,1" in Cameo-speak) and flip the x-coordinates
    # around the mean x-value (rotate by 90 degrees, mirror and shift x).
    # My proposed change: just swap x and y in the data (mirror about main diagonal)
    # This is easier and avoids utilizing landscape-mode.
    # Why should we bother? Pure technical reason: At the beginning of each cutting run,
    # Cameo makes a small "tick" in the margin of the media to align the blade.
    # This gives a small offset which is automatically compensated for in
    # portrait mode but not (correctly) in landscape mode.
    # As a result we get varying offsets which can be really annoying if doing precision
    # work.

    # Change by Sven Fabricius:
    # Update the code to use millimeters in all places to prevent mixing with device units.
    # The conversion to SU (SilhouetteUnits) will be done in command create function.
    # Removing all kinds of multiplying, dividing and rounding.

    if bbox is None: bbox = {}
    bbox['count'] = 0
    if not 'only' in bbox: bbox['only'] = False
    if 'clip' in bbox and 'urx' in bbox['clip']:
      flipwidth=bbox['clip']['urx']
    if 'clip' in bbox and 'llx' in bbox['clip']:
      x_off += bbox['clip']['llx']
    if 'clip' in bbox and 'ury' in bbox['clip']:
      y_off += bbox['clip']['ury']

    last_inside = True
    plotcmds=[]
    for path in plist:
      if len(path) < 2: continue
      x = path[0][0] + x_off
      y = path[0][1] + y_off
      _bbox_extend(bbox, x, y)
      bbox['count'] += 1

      x, y, last_inside = self.clip_point(x, y, bbox)

      if bbox['only'] is False:
        plotcmds.extend(self.move_mm_cmd(y, x))

      for j in range(1,len(path)):
        x = path[j][0] + x_off
        y = path[j][1] + y_off
        _bbox_extend(bbox, x, y)
        bbox['count'] += 1

        x, y, inside = self.clip_point(x, y, bbox)

        if bbox['only'] is False:
          if not self.enable_sw_clipping or (inside and last_inside):
            plotcmds.extend(self.draw_mm_cmd(y, x))
          else:
            # // if outside the range just move
            plotcmds.extend(self.move_mm_cmd(y, x))
        last_inside = inside
    return plotcmds
  

  def plot(self, mediawidth=210.0, mediaheight=297.0, margintop=None,
           marginleft=None, pathlist=None, offset=None, bboxonly=False,
           end_paper_offset=0, endposition='below', regmark=False, regsearch=False,
           regwidth=180, reglength=230, regoriginx=15.0, regoriginy=20.0):
    """plot sends the pathlist to the device (real or dummy) and computes the
       bounding box of the pathlist, which is returned.

       Each path in pathlist is rendered as a connected stroke (aka "pen_down"
       mode). Movements between paths are not rendered (aka "pen_up" mode).

       A path is a sequence of 2-tupel, all measured in mm.
           The tool is lowered at the beginning and raised at the end of each path.
       offset = (X_MM, Y_MM) can be specified, to easily move the design to the
           desired position.  The top and left media margin is always added to the
           origin. Default: margin only.
       bboxonly:  True for drawing the bounding instead of the actual cut design;
                  None for not moving at all (just return the bounding box).
                  Default: False for normal cutting or drawing.
       end_paper_offset: [mm] adds to the final move, if endposition is 'below'.
                If the end_paper_offset is negative, the end position is within the drawing
                (reverse movements are clipped at the home position)
                It reverse over the last home position.
       endposition: Default 'below': The media is moved to a position below the actual cut (so another
                can be started without additional steps, also good for using the cross-cutter).
                'start': The media is returned to the position where the cut started.
       Example: The letter Y (20mm tall, 9mm wide) can be generated with
                pathlist=[[(0,0),(4.5,10),(4.5,20)],[(9,0),(4.5,10)]]
    """
    bbox = { }
    if margintop  is None and 'margin_top_mm'  in self.hardware: margintop  = self.hardware['margin_top_mm']
    if marginleft is None and 'margin_left_mm' in self.hardware: marginleft = self.hardware['margin_left_mm']
    if margintop  is None: margintop = 0
    if marginleft is None: marginleft = 0

    # if 'margin_top_mm' in s.hardware:
    #   print("hardware margin_top_mm = %s" % (s.hardware['margin_top_mm']), file=s.log)
    # if 'margin_left_mm' in s.hardware:
    #   print("hardware margin_left_mm = %s" % (s.hardware['margin_left_mm']), file=s.log)

    if self.leftaligned and 'width_mm' in self.hardware:
      # marginleft += s.hardware['width_mm'] - mediawidth  ## FIXME: does not work.
      mediawidth = self.hardware['width_mm']

    print("mediabox: (%g,%g)-(%g,%g)" % (marginleft,margintop, mediawidth,mediaheight), file=self.log)

    width  = mediawidth
    height = mediaheight
    top    = margintop
    left   = marginleft
    if width < left: width  = left
    if height < top: height = top

    x_off = left
    y_off = top
    if offset is None:
      offset = (0,0)
    else:
      if type(offset) != type([]) and type(offset) != type(()):
        offset = (offset, 0)

    bbox['clip'] = {'urx':width, 'ury':top, 'llx':left, 'lly':height}
    bbox['only'] = bboxonly
    cmd_list = self.plot_cmds(pathlist,bbox,offset[0],offset[1])
    print("Final bounding box and point counts: " + str(bbox), file=self.log)

    if bboxonly == True:
      # move the bounding box
      cmd_list = [
        self.move_mm_cmd(bbox['ury'], bbox['llx']),
        self.draw_mm_cmd(bbox['ury'], bbox['urx']),
        self.draw_mm_cmd(bbox['lly'], bbox['urx']),
        self.draw_mm_cmd(bbox['lly'], bbox['llx']),
        self.draw_mm_cmd(bbox['ury'], bbox['llx'])]

    # potentially long command string needs extra care
    self.send_receive_command(cmd_list)

    # Silhouette Cameo2 does not start new job if not properly parked on left side
    # Attention: This needs the media to not extend beyond the left stop
    if not 'llx' in bbox: bbox['llx'] = 0  # survive empty pathlist
    if not 'lly' in bbox: bbox['lly'] = 0
    if not 'urx' in bbox: bbox['urx'] = 0
    if not 'ury' in bbox: bbox['ury'] = 0

    """
    if endposition == 'start':
        new_home = b"$H"
    else: #includes 'below'
      new_home = self.move_mm_cmd(bbox['lly'] + end_paper_offset, 0)
    self.send_receive_command(new_home)
    """
    new_home = [b"G01Z0F10", b"G01Y00F10"]
    self.send_receive_command(new_home)


    # Plotting is finished, raise tool and move to lly

    return {
        'bbox': bbox,
        'unit' : 1,
        'trailer': new_home
      }
  
  def move_origin(self, feed_mm):
    self.wait_for_ready()
    self.send_receive_command([
      b"G10L02P0Y%d" % feed_mm,
      b"G01Y0"
    ])
    self.wait_for_ready()

  def load_dumpfile(self,file):
    """ s is unused
    """
    data1234=None
    for line in open(file,'r').readlines():
      if re.match(r'\s*\[', line):
        exec('data1234='+line)
        break
      elif re.match(r'\s*<\s*svg', line):
        print(line)
        print("Error: xml/svg file. Please load into inkscape. Use extensions -> export -> sendto silhouette, [x] dump to file")
        return None
      else:
        print(line,end='')
    return data1234
  
  def wait_for_ready(self, timeout=30, poll_interval=2.0, verbose=False):
    # get_version() is likely to timeout here...
    # if verbose: print("device version: '%s'" % s.get_version(), file=sys.stderr)
    state = self.status()
    if self.dry_run:
      # not actually sending commands, so don't really care about being ready
      return state
    npolls = int(timeout/poll_interval)
    for i in range(1, npolls):
      if (state == 'ready'): break
      if (state == 'None'):
        raise NotImplementedError("Waiting for ready but no device exists.")
      if verbose: print(" %d/%d: status=%s\r" % (i, npolls, state), end='', file=sys.stderr)
      if verbose == False:
        if state == 'unloaded':
          print(" %d/%d: please load media ...\r" % (i, npolls), end='', file=sys.stderr)
        elif i > npolls/3:
          print(" %d/%d: status=%s\r" % (i, npolls, state), end='', file=sys.stderr)
      time.sleep(poll_interval)
      state = self.status()
    if verbose: print("",file=sys.stderr)
    return state
  
  def initialize(self):

    # Initial palaver
    print("Device Version: '%s'" % self.get_version(), file=self.log)


  def get_version(self):
    """Retrieve the firmware version string from the device."""
    return 'CutcutGo v1.0'

  def set_boundary(self, top, left, bottom, right):
    """ Sets boundary box """
    #self.send_command(["\\%d,%d" % (top, left), "Z%d,%d" % (bottom, right)])
    pass

  def set_cutting_mat(self, cuttingmat, mediawidth, mediaheight):
    """Setting Cutting mat only for Cameo 3 and 4

    Parameters
    ----------
        cuttingmat : any key in CAMEO_MATS or None
            type of the cutting mat
        mediawidth : float
            width of the media
        mediaheight : float
            height of the media
    """
    pass

  def setup(self, media=132, speed=None, pressure=None, toolholder=None, pen=None, cuttingmat=None, sharpencorners=False, sharpencorners_start=0.1, sharpencorners_end=0.1, autoblade=False, depth=None, sw_clipping=True, clip_fuzz=0.05, trackenhancing=False, bladediameter=0.9, landscape=False, leftaligned=None, mediawidth=210.0, mediaheight=297.0):
    """Setup the Silhouette Device

    Parameters
    ----------
        media : int, optional
            range is [100..300], "Print Paper Light Weight". Defaults to 132.
        speed : int, optional
            range is [1..10] for Cameo3 and older,
            range is [1..30] for Cameo4. Defaults to None, from paper (132 -> 10).
        pressure : int, optional
            range is [1..33], Notice: Cameo runs trackenhancing if you select a pressure of 19 or more. Defaults to None, from paper (132 -> 5).
        toolholder : int, optional
            range is [1..2]. Defaults to 1.
        pen : bool, optional
            media dependent. Defaults to None.
        cuttingmat : Any key in CAMEO_MATS, optional
            setting the cutting mat. Defaults to None.
        sharpencorners : bool, optional
            Defaults to False.
        sharpencorners_start : float, optional
            Defaults to 0.1.
        sharpencorners_end : float, optional
            Defaults to 0.1.
        autoblade : bool, optional
            Defaults to False.
        depth : int, optional
            range is [0..10] Defaults to None.
        sw_clipping : bool, optional
            Defaults to True.
        clip_fuzz : float, optional
            Defaults to 1/20 mm, the device resolution
        trackenhancing : bool, optional
            Defaults to False.
        bladediameter : float, optional
            Defaults to 0.9.
        landscape : bool, optional
            Defaults to False.
        leftaligned : bool, optional
            Loaded media is aligned left(=True) or right(=False). Defaults to device dependant.
        mediawidth : float, optional
            Defaults to 210.0.
        mediaheight : float, optional
            Defaults to 297.0.
    """


    if leftaligned is not None:
      self.leftaligned = leftaligned

    self.initialize()

    #self.set_cutting_mat(cuttingmat, mediawidth, mediaheight)

    if media is not None:
      if media < 100 or media > 300: media = 300

      if pen is None:
        if media == 113:
          pen = True
        else:
          pen = False
      for i in MEDIA:
        if i[0] == media:
          print("Media=%d, cap='%s', name='%s'" % (media, i[4], i[5]), file=self.log)
          if pressure is None: pressure = i[1]
          if speed is None:    speed = i[2]
          if depth is None:    depth = i[3]
          break

    # Select the right toolholder
    self.send_receive_command([b'T%d' % toolholder, b'$H'])
    self.tool_up = True

    print("toolholder: %d" % toolholder, file=self.log)

    self.enable_sw_clipping = sw_clipping
    self.clip_fuzz = clip_fuzz
 

  def find_bbox(self, cut):
    """Find the bounding box of the cut, returns (xmin,ymin,xmax,ymax)"""
    bb = {}
    for path in cut:
      for pt in path:
        _bbox_extend(bb,pt[0],pt[1])
    return bb

  def flip_cut(self, cut):
    """this returns a flipped copy of the cut about the y-axis,
       keeping min and max values as they are."""
    bb = self.find_bbox(cut)
    new_cut = []
    for path in cut:
      new_path = []
      for pt in path:
        new_path.append((pt[0], bb['lly']+bb['ury']-pt[1]))
      new_cut.append(new_path)
    return new_cut

  def mirror_cut(self, cut):
    """this returns a mirrored copy of the cut about the x-axis,
       keeping min and max values as they are."""
    bb = self.find_bbox(cut)
    new_cut = []
    for path in cut:
      new_path = []
      for pt in path:
        new_path.append((bb['llx']+bb['urx']-pt[0], pt[1]))
      new_cut.append(new_path)
    return new_cut