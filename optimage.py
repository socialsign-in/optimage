# Copyright 2015 Sebastian Kreft
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import collections
import logging
import os.path
import shutil
import subprocess
import sys
import tempfile
import re


from PIL import Image

TEMP_DIR=None
SIMILARITY_THRESHOLD=5



class CompressionSimilarityError(Exception):
    pass

def _images_are_similar(filename1,filename2):
    try:
        import pHash
    except FileNotFoundError, fe:
        logging.info("Could not determine similarity - missing pHash module") 
        return True
    
    hash1 = pHash.imagehash(filename1)
    hash2 = pHash.imagehash(filename2)
    hd = pHash.hamming_distance(hash1,hash2)
    logging.info('Hamming distance: %d (%08x / %08x)' % ( hd, hash1, hash2 ))

    if hd <= SIMILARITY_THRESHOLD:
        return True

    return False
    
    """
    digest1 = pHash.image_digest(filename1, 1.0, 1.0, 180 )
    digest2 = pHash.image_digest(filename2, 1.0, 1.0, 180 )
    print 'Cross-correelation: %d' % ( pHash.crosscorr( digest1, digest2 ) )
    """


def _images_are_equal(filename1, filename2):
    # We need to convert both images to the same format, as the resulting one
    # may have lost the alpha channel (alpha=255) or may be now indexed
    # (L or P mode).
    # We also need to check whether the alpha value is '\x00' in which case the
    # RGB value is not important.
    img1 = Image.open(filename1).convert('RGBA')
    img2 = Image.open(filename2).convert('RGBA')

    img1_bytes = img1.tobytes()
    img2_bytes = img2.tobytes()
    

    if len(img1_bytes) != len(img2_bytes):
        return False

    # HACK to support comparison in both Python 2 and 3. Subscripting a
    # bytes (string) in Python 2 returns a string, whereas in Python 3 returns
    # ints.
    null_byte = b'\x00'[0]
    for i in range(len(img1_bytes) // 4):
        pos = 4 * i
        if (img1_bytes[pos + 3] == null_byte and
                img2_bytes[pos + 3] == null_byte):
            continue

        if img1_bytes[pos:pos + 4] != img2_bytes[pos:pos + 4]:
            return False

    return True


# Magic numbers taken from https://en.wikipedia.org/wiki/List_of_file_signatures
_JPEG_MAGIC_NUMBER = b'\xFF\xD8\xFF'
_PNG_MAGIC_NUMBER = b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'


def _check_magic_number(filename, magic_number):
    """Check whether the filename starts with the provided magic number."""
    with open(filename, 'rb') as f:
        return f.read(len(magic_number)) == magic_number


def _is_jpeg(filename):
    """Check whether the filename is a valid JPEG file."""
    return _check_magic_number(filename, _JPEG_MAGIC_NUMBER)


def _is_png(filename):
    """Check whether the filename is a valid PNG file."""
    return _check_magic_number(filename, _PNG_MAGIC_NUMBER)


"""
Change this to use the same directory
"""
def _get_temporary_filename(prefix='tmp'):
    temp_file = tempfile.NamedTemporaryFile(prefix=prefix,dir=TEMP_DIR)
    temp_name = temp_file.name
    temp_file.close()

    return temp_name


class InvalidExtension(Exception):
    """The file extension does not correspond to the file contents."""


if sys.version_info.major == 2:
  FileNotFoundError = OSError
else:
  FileNotFoundError = FileNotFoundError


class MissingBinary(FileNotFoundError):
    """The binary does not exist."""


def _call_binary(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.STDOUT)
    except FileNotFoundError as error:
        raise MissingBinary(error.errno, 'binary not found', args[0])


def _pngcrush(input_filename, output_filename):
    _call_binary(['pngcrush', '-rem', 'alla', '-reduce', '-brute', '-q',
                  input_filename, output_filename])

def _pngcrush_fast(input_filename, output_filename):
    _call_binary(['pngcrush',input_filename, output_filename])

def _pngquant(input_filename, output_filename, quality=100):
    _call_binary(['pngquant', '--force', '--speed', '1', '--quality', str(quality),
                  '--output', output_filename, input_filename])


def _parse_gifsicle_frame_line(line):
    if 'delay' in line:
        delay = float(line.split()[-1].replace('s',''))
        return { 'delay': delay }
    elif 'compressed' in line:
        size = int(line.split()[-1].replace('s',''))
        return { 'size': size }
    if '+' in line:
        image_info = line.split() 
        res = {}
        m = re.search('\+ +image (?P<index>#[0-9]+) (?P<dimensions>\d*x\d*)? ?(at (?P<offset>\d,\d))? ?(?P<bg>\w+) ?(?P<colors>\d+)',line) 
        for grouping in ['index','dimensions','offset','bg','colors']:
            try:
                res[grouping] = m.group(grouping)
            except IndexError:
                pass
        return res 
         

        
        

def _gifsicle_info(input_filename):
    result = _call_binary(['gifsicle', '--sinfo', input_filename])
    data = result.split("\n")
    frames = []
    file_data = {} 
    screen_parts = data[1].split()
    color_parts = data[2].split()
    bg_parts = data[3].split()
    
    width,height = screen_parts[2].split('x')
    file_data['width'] = int(width)
    file_data['height'] = int(height)
   
    frame_data = data[4:]
    frames_index = 0
    
    while frames_index < len(frame_data)-1:
         
        res = _parse_gifsicle_frame_line(frame_data[frames_index])
        if not res:
            frames_index += 1
            continue
        if 'index' in res: 
            frames.append(res.copy()) 
        else:
            frames[-1].update(res)
            
        frames_index += 1
        
    
    file_data['frames'] = frames
    return file_data


"""
Optimize levels
-O1
-O2
-O3
"""
def _gifsicle(input_filename, output_filename, lossy=80, optimize_level=3, resize=None, crop=None, frame_reduce=1):
    if resize:
        _call_binary(['gifsicle', '--resize-fit-width=%s' % str(resize[0]), '--resize-fit-height=%s' % str(resize[1]), '-o', output_filename, 
                   input_filename])
    elif crop:
        _call_binary(['gifsicle', '--crop=%s,%s-%s,%s' % (crop[0],crop[1],crop[2],crop[3]), '-o', output_filename, 
                   input_filename])
    else:
        _call_binary(['gifsicle', '--lossy=%s' % str(lossy), '-o', output_filename, '-O%s' % str(optimize_level),
                   input_filename])

def _optipng(input_filename, output_filename):
    _call_binary(['optipng', '-out', output_filename, '-o9', '-quiet',
                  input_filename])

def _zopflipng(input_filename, output_filename):
    _call_binary(['zopflipng', '-m', '--lossy_8bit', '--lossy_transparent',
                  '--filters=0me', input_filename, output_filename])


def _jpegtran(input_filename, output_filename):
    _call_binary(['jpegtran', '-copy', 'none', '-optimize', '-perfect',
                  '-outfile', output_filename, input_filename])


def _jpegoptim(input_filename, output_filename):
    # jpegoptim replaces the input file with the compressed version, so we first
    # need to copy the input file to the output file.
    shutil.copy(input_filename, output_filename)
    _call_binary(['jpegoptim', '--strip-all', '--quiet', output_filename])


_CompressorResult = collections.namedtuple('_CompressorResult',
                                           ['size', 'filename', 'compressor'])


def _process(input_filename, compressor, **kwargs):
    """Helper function to compress an image.

    Returns:
      _CompressorResult named tuple, with the resulting size and the temporary
      filename used.
    """
    result_filename = _get_temporary_filename(prefix=compressor.__name__)

    compressor(input_filename, result_filename, **kwargs)
    result_size = os.path.getsize(result_filename)

    return _CompressorResult(result_size, result_filename, compressor.__name__)


def modify_size(input_filename, compressor, **kwargs):
    result = _process(input_filename, compressor, **kwargs) 
    newfile_info = _gifsicle_info(result.filename)

    if kwargs.get('resize'):
        if newfile_info['width'] == kwargs.get('resize')[0] and newfile_info['height'] == kwargs.get('resize')[1]:
            shutil.copyfile(result.filename, input_filename)
        else:
            logging.info("Failed to resize properly")
    elif kwargs.get('crop'):
        crop_info = kwargs.get('crop')
        exp_height = crop_info[2]-crop_info[0]
        exp_width = crop_info[3]-crop_info[1]
        if newfile_info['width'] == exp_width and newfile_info['height'] == exp_height:
            shutil.copyfile(result.filename, input_filename)
        else:
            logging.info("Failed to crop properly")

        
         
    return (input_filename,newfile_info['width'],newfile_info['height']) 

def _compress_with(input_filename, output_filename, compressors, **kwargs):
    """Helper function to compress an image with several compressors.

    In case the compressors do not improve the filesize or in case the resulting
    image is not equivalent to the source, then the output will be a copy of the
    input.
    """
    results = [
        _process(input_filename, compressor, **kwargs) for compressor in compressors]
    best_result = min(results)
    os.rename(best_result.filename, output_filename)

    best_compressor = best_result.compressor
    if (best_result.size >= os.path.getsize(input_filename)):
        best_compressor = None

    if best_compressor is not None:
        if not SIMILARITY_THRESHOLD:
            logging.info("Not comparing images because Similarity threshold is 0")
            logging.info('%s: best compressor for "%s"', best_compressor,
                 input_filename)
            return

        if best_compressor not in ['_pngquant', '_gifsicle']:
            if not _images_are_equal(input_filename, output_filename):
                logging.info('Comparing Equal %s: %s -> %s' % (best_compressor,input_filename,output_filename))
                shutil.copy(input_filename, output_filename)
                raise CompressionSimilarityError("compressor %s produced distant files" % best_compressor)
        else:
            if not _images_are_similar(input_filename, output_filename):
                logging.info('Comparing Similarity %s: %s -> %s' % (best_compressor,input_filename,output_filename))
                shutil.copy(input_filename, output_filename)
                raise CompressionSimilarityError("compressor %s produced distant files" % best_compressor)

    
    if best_compressor is None:
        logging.info("copying %s -> %s becuase we had no compression" % (input_filename, output_filename))
        shutil.copy(input_filename, output_filename)

    logging.info('%s: best compressor for "%s"', best_compressor,
                 input_filename)


def jpeg_compressor(input_filename, output_filename):
    """Loslessly recompress a JPEG.

    Raises:
      InvalidExtension in case the input is not a JPEG.
    """
    if not _is_jpeg(input_filename):
        raise InvalidExtension()

    _compress_with(input_filename, output_filename, [_jpegtran, _jpegoptim])


def png_compressor(input_filename, output_filename):
    """Loslessly recompress a JPEG.

    Raises:
      InvalidExtension in case the input is not a PNG.
    """
    if not _is_png(input_filename):
        raise InvalidExtension()

    _compress_with(input_filename, output_filename,
                   [_pngcrush, _optipng, _zopflipng])


_EXTENSION_MAPPING = {
    '.jpeg': jpeg_compressor,
    '.jpg': jpeg_compressor,
    '.png': png_compressor,
}


def _parse_argv(argv):
    parser = argparse.ArgumentParser(
        description='Losslessly compress JPEG and PNG files.',
        prog='optimage')
    parser.add_argument(
        '--replace',
        action='store_true',
        help='replace the input file in case we can compress it')
    parser.add_argument('filename',
                        action='store',
                        help='the filename to compress')
    parser.add_argument('--output',
                        action='store',
                        help='the filename to compress',
                        required=False)
    parser.add_argument('--debug', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    return args


def main(argv):
    args = _parse_argv(argv)
    filename = args.filename

    if not os.path.isfile(filename):
        sys.stderr.write(
            '{} is not an image file\n'.format(filename))
        return 3

    _, extension = os.path.splitext(filename)
    extension = extension.lower()
    compressor = _EXTENSION_MAPPING.get(extension)
    if compressor is None:
        sys.stderr.write(
            'No lossless compressor defined for extension "{}"\n'.format(
                extension))
        return 4

    if args.debug:
        logging.basicConfig(level=logging.INFO,
                            format='%(levelname)s: %(message)s')

    output_filename = _get_temporary_filename(prefix='lossless-compressor')
    try:
        compressor(filename, output_filename)
    except InvalidExtension as error:
        sys.stderr.write(
            '{} is not a "{}" file. Please correct the extension\n'.format(
                filename, extension))
        return 5
    except MissingBinary as error:
        sys.stderr.write(
            'The executable "{}" was not found. '.format(error.filename) +
            'Please install it and re-run this command.\n')
        return 6
    except subprocess.CalledProcessError as error:
        sys.stderr.write(
            'Error when running the command:\n  ' +
            '{}\n'.format(' '.join(error.cmd)))
        sys.stderr.write('Status: {}\n'.format(error.returncode))
        sys.stderr.write('Output:\n')
        sys.stderr.write(error.output.decode('utf-8'))
        return 7

    original_size = os.path.getsize(filename)
    new_size = os.path.getsize(output_filename)
    reduction = original_size - new_size
    reduction_percentage = reduction * 100 / original_size
    savings = 'savings: {} bytes = {:.2f}%'.format(
        reduction, reduction_percentage)

    if new_size < original_size:
        if args.replace or args.output is not None:
            if args.replace:
                shutil.copy(output_filename, filename)
            else:
                shutil.copy(output_filename, args.output)

            print('File was losslessly compressed to {} bytes ({})'.format(
                new_size, savings))
            return 0
        else:
            print(
                'File can be losslessly compressed to {} bytes ({})'.format(
                    new_size, savings))
            print('Replace it by running either:')
            print('  optimage --replace {}'.format(filename))
            print('  optimage --output <FILENAME> {}'.format(filename))
            return 1

    return 0


__all__ = (jpeg_compressor, png_compressor)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))  # pragma: no cover
