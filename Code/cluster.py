import os
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np
import struct
import re
import zipfile
import shutil

# =============================================================================
# Masks
# =============================================================================

SignatureMask    = 0xC0000000    # 1100 0000 0000 0000 0000 0000 0000 0000
SubSignatureMask = 0x3FE00000    # 0011 1111 1110 0000 0000 0000 0000 0000

ModuleMask       = 0x00FF0000    # 0000 0000 1111 1111 0000 0000 0000 0000
ChannelMask      = 0x001F0000    # 0000 0000 0001 1111 0000 0000 0000 0000
ADCMask          = 0x00003FFF    # 0000 0000 0000 0000 0011 1111 1111 1111
ExTsMask         = 0x0000FFFF    # 0000 0000 0000 0000 1111 1111 1111 1111
TimeStampMask 	 = 0x3FFFFFFF    # 0011 1111 1111 1111 1111 1111 1111 1111
WordCountMask  	 = 0x00000FFF    # 0000 0000 0000 0000 0000 1111 1111 1111


# =============================================================================
# Dictionary
# =============================================================================

Header        	 = 0x40000000    # 0100 0000 0000 0000 0000 0000 0000 0000
Data          	 = 0x00000000    # 0000 0000 0000 0000 0000 0000 0000 0000
EoE           	 = 0xC0000000    # 1100 0000 0000 0000 0000 0000 0000 0000

DataEvent        = 0x04000000    # 0000 0100 0000 0000 0000 0000 0000 0000
DataExTs         = 0x04800000    # 0000 0100 1000 0000 0000 0000 0000 0000


# =============================================================================
# Bit shifts
# =============================================================================

ChannelShift     = 16
ModuleShift      = 16
ExTsShift        = 30


# =============================================================================
# CLUSTER DATA
# =============================================================================

def cluster_data(data, ADC_to_Ch, window):
    """ Clusters the imported data and stores it two data frames: one for 
        individual events and one for coicident events (i.e. candidate neutron 
        events).
        
        Does this in the following fashion for coincident events:
            1. Reads one word at a time
            2. Checks what type of word it is (Header, BusStart, DataEvent,
               DataExTs or EoE).
            3. When a Header is encountered, 'isOpen' is set to 'True',
               signifying that a new event has been started. Data is then
               gathered into a single coincident event until a different bus is
               encountered (unless ILL exception), in which case a new event is
               started.
            4. When EoE is encountered the event is formed, and timestamp is 
               assigned to it and all the created events under the current 
               Header. This event is placed in the created dictionary.
            5. After the iteration through data is complete, the dictionary
               containing the coincident events is convereted to a DataFrame.
           
    Args:
        data (tuple)    : Tuple containing data, one word per element.
        ILL_buses (list): List containg all ILL buses
            
    Returns:
        data (tuple): A tuple where each element is a 32 bit mesytec word
        
        events_df (DataFrame): DataFrame containing one event (wire or grid) 
                               per row. Each event has information about:
                               "Bus", "Time", "Channel", "ADC".
        
    """
    # Initiate dictionaries to store data
    size = len(data)
    if window.MG_CNCS.isChecked():
        attributes = ['wADC_1', 'wADC_2', 'wChADC_1', 'wChADC_2',
                      'gADC_1', 'gADC_2', 'gChADC_1', 'gChADC_2']
        channels = ['wCh_1', 'wCh_2', 'gCh_1', 'gCh_2']
    else:
        attributes = ['gADC_1', 'gADC_2', 'gChADC_1', 'gChADC_2',
                      'wADC_1', 'wADC_2', 'wChADC_1', 'wChADC_2',
                      'wADC_3', 'wADC_4', 'wChADC_3', 'wChADC_4'
                      ]
        channels = ['wCh_1', 'wCh_2', 'wCh_3', 'wCh_4', 'gCh_1', 'gCh_2']
    events = {'Module': np.zeros([size], dtype=int),
              'ToF': np.zeros([size], dtype=int)
              }
    for attribute in attributes:
        events.update({attribute: np.zeros([size], dtype=int)})
    for channel in channels:
        events.update({channel: np.zeros([size], dtype=int)})
    # Declare parameters
    wires_or_grids = {'w': 'Wires', 'g': 'Grids'}
    #Declare temporary variables
    isOpen = False
    index = 0
    #Four possibilities in each word: Header, DataEvent, DataExTs or EoE.
    for i, word in enumerate(data):
        if (word & SignatureMask) == Header:
            # Extract values
            Module = (word & ModuleMask) >> ModuleShift
            events['Module'][index] = Module
            # Adjust temporary variables
            isOpen = True
        elif ((word & SignatureMask) == Data) & isOpen:
            # Extract values
            ADC = (word & ADCMask)
            Channel = ((word & ChannelMask) >> ChannelShift)
            attribute = attributes[Channel]
            events[attribute][index] = ADC
            # Check if wire or grid
            w_or_g = wires_or_grids[attribute[:1]]
            # Get discreet channel
            if len(attribute) == 8:
                physical_Ch = ADC_to_Ch[w_or_g][ADC]
                channel_attribute = attribute[0:3] + attribute[-2:]
                events[channel_attribute][index] = physical_Ch
        elif ((word & SignatureMask) == EoE) & isOpen:
            # Extract values
            ToF = (word & TimeStampMask)
            events['ToF'][index] = ToF
            # Increase index and reset temporary variables
            isOpen = False
            index += 1

    #Remove empty elements and save in DataFrame for easier analysis
    for key in events:
        events[key] = events[key][0:index]
    events_df = pd.DataFrame(events)
    return events_df


# =============================================================================
# Helper Functions
# =============================================================================

def mkdir_p(mypath):
    '''Creates a directory. equivalent to using mkdir -p on the command line'''

    from errno import EEXIST
    from os import makedirs, path

    try:
        makedirs(mypath)
    except OSError as exc:
        if exc.errno == EEXIST and path.isdir(mypath):
            pass
        else:
            raise


def get_ADC_to_Ch():
    # Declare parameters
    layers_dict = {'Wires': 16, 'Grids': 12}
    delimiters_table = import_delimiter_table()
    channel_mapping = import_channel_mappings()
    print(channel_mapping['Wires'])
    ADC_to_Ch = {'Wires': {i: -1 for i in range(4096)},
                 'Grids': {i: -1 for i in range(4096)}}
    for key, delimiters in delimiters_table.items():
        layers = layers_dict[key]
        print(key)
        for i, (start, stop) in enumerate(delimiters):
            # Get channel mapping and delimiters
            channel = channel_mapping[key][i]
            small_delimiters = np.linspace(start, stop, layers+1)
            # Iterate through small delimiters
            previous_value = small_delimiters[0]
            for j, value in enumerate(small_delimiters[1:]):
                channel = channel_mapping[key][i*layers+j]
                print('i: %s, Ch: %s' % (str(i*layers+j), str(channel)))
                start, stop = int(round(previous_value)), int(round(value))
                # Assign ADC->Ch mapping for all values within interval
                for k in np.arange(start, stop, 1):
                    ADC_to_Ch[key][k] = channel
                previous_value = value
    return ADC_to_Ch


def import_channel_mappings():
    dirname = os.path.dirname(__file__)
    path = os.path.join(dirname, '../Tables/Grid_Wire_Channel_Mapping.xlsx')
    matrix = pd.read_excel(path).values
    wires, grids = [], []
    for row in matrix[1:]:
        wires.append(row[1])
        if not np.isnan(row[3]):
            grids.append(np.array(row[3]))
    return {'Wires': np.array(wires), 'Grids': np.array(grids)}


def import_delimiter_table():
    dirname = os.path.dirname(__file__)
    path = os.path.join(dirname, '../Tables/Histogram_delimiters.xlsx')
    matrix = pd.read_excel(path).values
    wires, grids = [], []
    for row in matrix[1:]:
        wires.append(np.array([row[0], row[1]]))
        if not np.isnan(row[2]):
            grids.append(np.array([row[2], row[3]]))
    return {'Wires': np.array(wires), 'Grids': np.array(grids)}




