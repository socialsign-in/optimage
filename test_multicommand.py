import os
import shutil
import subprocess

import pytest
try:
  import pytest_catchlog
  catchlog_available = True
except ImportError:
  catchlog_available = False

import optimage
import logging


def test_gifsicle_info_76(): 
    data_file = 'test_data/76frame.gif'
    res = optimage._gifsicle_info(data_file)
    assert(len(res['frames']) == 76)

def test_gifsicle_info_12(): 
    data_file = 'test_data/loader.gif'
    res = optimage._gifsicle_info(data_file)
    assert(len(res['frames']) == 12)

def test_gifsicle_resize(): 
    data_file = 'test_data/loader.gif'
    new_file = 'test_data/loader_tmp.gif'
    shutil.copyfile(data_file,new_file)
    resize = (16,16)
    res = optimage.modify_size(new_file, optimage._gifsicle, resize=resize)
    assert(res[0] == new_file)
    assert(res[1] == resize[0])
    assert(res[2] == resize[1])

    os.remove(new_file)


def test_gifsicle_resize_aspect(): 
    #'700x617'
    data_file = 'test_data/76frame.gif'
    new_file = 'test_data/loader_tmp.gif'
    shutil.copyfile(data_file,new_file)
    res = optimage._gifsicle_info(new_file)
 
    resize = (350,309)
    res = optimage.modify_size(new_file, optimage._gifsicle, resize=resize)
    assert(res[0] == new_file)
    assert(res[1] == resize[0] or res[1] == resize[0] + 1)
    assert(res[2] == resize[1])

    os.remove(new_file)



def test_gifsicle_crop(): 
    #'700x617'
    data_file = 'test_data/76frame.gif'
    new_file = 'test_data/loader_tmp.gif'
    shutil.copyfile(data_file,new_file)
    res = optimage._gifsicle_info(new_file)
 
    crop = (150,17,550,417)
    res = optimage.modify_size(new_file, optimage._gifsicle, crop=crop)
    assert(res[0] == new_file)
    assert(res[1] == 400)
    assert(res[2] == 400)

    os.remove(new_file)
