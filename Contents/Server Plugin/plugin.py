#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2018, Kieran J. Broadfoot. All rights reserved.
# http://kieranbroadfoot.com
#

import sys
import tempfile
import zipfile
from xmljson import badgerfish as bf
from xml.etree.ElementTree import fromstring
import shutil
import socket
import struct
import json
import math
import os

EIB_OPEN_GROUPCON = 0x26
EIB_GROUP_PACKET = 0x27

KNXWRITE = 0x80
KNXREAD = 0x00

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.knxLocation = pluginPrefs.get("knxNetworkLocation", "192.168.0.10")
        self.knxPort = int(pluginPrefs.get("knxNetworkPort", "6720"))
        self.knxConnectionType = pluginPrefs.get("knxConnectionType", "knxd")
        self.knxDebug = pluginPrefs.get("knxDebug", False)
        self.stopThread = False
        self.groupAddresses = {}
        self.statusAddresses = {}
        self.validConnections = False
        self.knxSocket = None
        self.globalBuffer = bytearray()

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def startup(self):
        try:
            self.groupAddresses = json.loads(self.pluginPrefs["group_addresses"])
        except Exception as e:
            pass
        self.generateStatusAddresses()

    def shutdown(self):
        self.logger.info("stopping knx plugin")
        if self.validConnections:
            self.knxSocket.close()
            
    def generateStatusAddresses(self):
        for device in indigo.devices.iter("self"):
            for prop in device.pluginProps:
                if "status_" in prop:
                    self.statusAddresses[device.pluginProps[prop]] = (prop, device.id, device.deviceTypeId)

    def validatePrefsConfigUi(self, valuesDict):
        success = False
        errorDict = indigo.Dict()
        if self.loadConnections(valuesDict["knxNetworkLocation"], int(valuesDict["knxNetworkPort"])):
            self.knxLocation = valuesDict["knxNetworkLocation"]
            self.knxPort = int(valuesDict["knxNetworkPort"])
            self.knxDebug = valuesDict["knxDebug"]
            success = True
        else:
            errorDict["knxNetworkLocation"] = "Cannot connect"
        if valuesDict["knxGALoader"] == True:
            xmlns = "{http://knx.org/xml/project/14}"
            if valuesDict["knxWizardETS4"] == True:
                xmlns = "{http://knx.org/xml/project/12}"
            filename = valuesDict["knxWizardETS5Path"]
            if os.path.exists(filename) and os.path.isfile(filename):
                self.logger.info("parsing group addresses from knxproj file (namespace: "+xmlns+")")
                path_to_temp_dir = tempfile.mkdtemp()
                fantasy_zip = zipfile.ZipFile(filename)
                fantasy_zip.extractall(path_to_temp_dir)
                fantasy_zip.close()
                group_addresses = {}
                with open(path_to_temp_dir+"/P-02CD/0.xml", 'r') as project:
                    data = bf.data(fromstring(project.read()))
                    location = ""
                    room = ""
                    for key, value in data[xmlns+"KNX"][xmlns+"Project"][xmlns+"Installations"][xmlns+"Installation"][xmlns+"GroupAddresses"][xmlns+"GroupRanges"].items():
                        location = value["@Name"]
                        for room_keys, room_values in value[xmlns+"GroupRange"].items():
                            if room_keys == "@Name":
                                room = room_values
                            if room_keys == xmlns+"GroupAddress":
                                for ga in room_values:
                                    group_addresses[ga["@Address"]] = {
                                        "address": ga["@Address"],
                                        "name": ga["@Name"],
                                        "id": ga["@Id"],
                                        "room": room,
                                        "location": location,
                                        "list_string": str(self.decode_ga(ga["@Address"]))+" ("+ga["@Name"]+" / "+room+")"
                                    }
                shutil.rmtree(path_to_temp_dir)
                valuesDict["group_addresses"] = json.dumps(group_addresses)
            else:
                errorDict["knxWizardETS5Path"] = "No such file"
                success = False
        return (success, valuesDict, errorDict)

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        success = True
        errorDict = indigo.Dict()
        count = 0
        for device in indigo.devices.iter("self"):
            num = int(device.address.split(':', 1)[-1])
            if num > count:
                count = num
        valuesDict["address"] = "knx:"+str(count+1)
        if typeId == "knxSwitch":
            if valuesDict["enterManually"] == False:
                valuesDict["set_onoff"] = self.decode_ga(int(valuesDict["knxSwitchSetGroupAddress"]))
                valuesDict["status_onoff"] = self.decode_ga(int(valuesDict["knxSwitchStatusGroupAddress"]))
            else:
                valuesDict["set_onoff"] = valuesDict["knxSwitchSetGroupAddressManual"]
                valuesDict["status_onoff"] = valuesDict["knxSwitchStatusGroupAddressManual"]
        elif typeId == "knxDimmer":
            if valuesDict["enterManually"] == False:
                valuesDict["set_onoff"] = self.decode_ga(int(valuesDict["knxDimmerSetOnOffGroupAddress"]))
                valuesDict["status_onoff"] = self.decode_ga(int(valuesDict["knxDimmerStatusOnOffGroupAddress"]))
                valuesDict["set_absdim"] = self.decode_ga(int(valuesDict["knxDimmerSetAbsDimGroupAddress"]))
                valuesDict["set_reldim"] = self.decode_ga(int(valuesDict["knxDimmerSetRelDimGroupAddress"]))
                valuesDict["status_brightness"] = self.decode_ga(int(valuesDict["knxDimmerStatusBrightnessGroupAddress"]))
            else:
                valuesDict["set_onoff"] = valuesDict["knxDimmerSetOnOffGroupAddressManual"]
                valuesDict["status_onoff"] = valuesDict["knxDimmerStatusOnOffGroupAddressManual"]
                valuesDict["set_absdim"] = valuesDict["knxDimmerSetAbsDimGroupAddressManual"]
                valuesDict["set_reldim"] = valuesDict["knxDimmerSetRelDimGroupAddressManual"]
                valuesDict["status_brightness"] = valuesDict["knxDimmerStatusBrightnessGroupAddressManual"]
        elif typeId == "knxPir":
            self.logger.info("Creating PIR")
            self.logger.info(valuesDict)
            if valuesDict["enterManually"] == False:
                valuesDict["status_onoff"] = self.decode_ga(int(valuesDict["knxPirStatusGroupAddress"]))
            else:
                valuesDict["status_onoff"] = valuesDict["knxPirStatusGroupAddressManual"]
            self.logger.info(valuesDict)
        elif typeId == "knxSensor":
            if valuesDict["enterManually"] == False:
                valuesDict["status_onoff"] = self.decode_ga(int(valuesDict["knxSensorStatusGroupAddress"]))
            else:
                valuesDict["status_onoff"] = valuesDict["knxSensorStatusGroupAddressManual"]
        elif typeId == "knxLightSensor":
            if valuesDict["enterManually"] == False:
                valuesDict["status_lux"] = self.decode_ga(int(valuesDict["knxLightSensorStatusGroupAddress"]))
            else:
                valuesDict["status_lux"] = valuesDict["knxLightSensorStatusGroupAddressManual"]
        elif typeId == "knxTemperatureSensor":
            if valuesDict["enterManually"] == False:
                valuesDict["status_temperature"] = self.decode_ga(int(valuesDict["knxTempSensorStatusGroupAddress"]))
            else:
                valuesDict["status_temperature"] = valuesDict["knxTempSensorStatusGroupAddressManual"]
        else:
            self.logger.warn("knx device not yet supported")
            success = False
        return (success, valuesDict, errorDict)
        
    def deviceStartComm(self, dev):
        if dev.deviceTypeId == "knxSensor":
            dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
        elif dev.deviceTypeId == "knxLightSensor":
            dev.updateStateImageOnServer(indigo.kStateImageSel.LightSensor)
        elif dev.deviceTypeId == "knxTemperatureSensor":
            dev.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensor)
        self.generateStatusAddresses()

    ########################################
    # MONITORING
    ########################################

    def runConcurrentThread(self):
        self.logger.info("starting knx monitoring thread")
        while True and self.stopThread == False:
            # if self.readerSocket != None:
            if self.knxSocket != None:
                try:
                    while self.stopThread == False:
                        try:
                            raw_data = self.knxSocket.recv(1024)
                            # add raw_data to global buffer and then parse it to see if we can find messages
                            for i in raw_data:
                                self.globalBuffer.extend(i)
                            messages = self.parseBuffer()
                            for message in messages:
                                if len(message) > 2:
                                    (src, dst, value) = self.decode_message(message)
                                    if dst in self.statusAddresses:
                                        self.updateIndigoState(value, self.statusAddresses[dst])
                            messages = []
                        except Exception as e:
                            continue
                except Exception:
                    # unable to send to socket... catches error on shutdown
                    continue
            else:
                self.logger.info("not connected to knx. re-try in 10 seconds")
                self.sleep(10)

    def stopConcurrentThread(self):
        if self.knxSocket != None:
            self.knxSocket.close()
        self.stopThread = True

    def parseBuffer(self):
        mesgs = []
        while True:
            try:
                telegram_length = (self.globalBuffer[0] << 0 | self.globalBuffer[1])
                if len(self.globalBuffer) < telegram_length + 2:
                    return mesgs
                else:
                    # pull off the requisite number of bytes and add to messages
                    mesgs.append(self.globalBuffer[0:telegram_length+2])
                    del self.globalBuffer[0:telegram_length+2]
            except Exception as e:
                return mesgs

    def updateIndigoState(self, value, props):
        statusField = props[0].split("_")[1]
        deviceId = props[1]
        deviceType = props[2]
        dev = indigo.devices[deviceId]
        if deviceType == "knxSwitch":
            if value == 0:
                dev.updateStateOnServer("onOffState", False)
            else:
                dev.updateStateOnServer("onOffState", True)
        elif deviceType == "knxDimmer":
            if value == 0:
                dev.updateStateOnServer("onOffState", False)
            elif value == 1 and statusField == "onoff":
                # ignore - will receive brightness status
                return
                # dev.updateStateOnServer("onOffState", True)
                # dev.updateStateOnServer("brightnessLevel", 100)
            elif statusField == "brightness":
                local_value = math.ceil(int(value)/2.55)
                dev.updateStateOnServer("onOffState", True)
                dev.updateStateOnServer("brightnessLevel", local_value)
            else:
                self.logger.warn("dimmer: unexpected status message received")
        elif deviceType == "knxPir":
            if value == 1:
                dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
                dev.updateStateOnServer("onOffState", False)
            else:
                dev.updateStateImageOnServer(indigo.kStateImageSel.MotionSensorTripped)
                dev.updateStateOnServer("onOffState", True)
        elif deviceType == "knxSensor":
            if value == 1:
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                dev.updateStateOnServer("onOffState", False)
            else:
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                dev.updateStateOnServer("onOffState", True)
        elif deviceType == "knxLightSensor":
            dev.updateStateImageOnServer(indigo.kStateImageSel.LightSensor)
            dev.updateStateOnServer("sensorValue", value)
        elif deviceType == "knxTemperatureSensor":
            dev.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensor)
            dev.updateStateOnServer("sensorValue", value)
        else:
            self.logger.warn("received status message from unexpected device")

    ########################################
    # COMMUNICATION (WITH KNX) FUNCTIONS
    ########################################
    
    def loadConnections(self, location, port):
        while True:
            try:
                self.knxSocket = socket.create_connection((location, port),2)
                if self.knxSocket.fileno != -1:
                    self.knxSocket.send(self.encode_data('HHB', [EIB_OPEN_GROUPCON, 0, 0]))
                    self.logger.info("connected to knx at "+location)
                    return True
                else:
                    self.logger.warn("no valid knx endpoint.")
                    self.sleep(10)
            except Exception:
                self.logger.warn("unable to connect to knx at "+location)
                self.sleep(10)

    def writeToKNX(self, type, group_address, value):
        while True:
            try:
                if type == "1.x":
                    self.knxSocket.send(self.encode_data('HHBB', [EIB_GROUP_PACKET, self.encode_ga(group_address), 0, KNXWRITE | value]))
                elif type == "5.x":
                    self.knxSocket.send(self.encode_data('HHBBB', [EIB_GROUP_PACKET, self.encode_ga(group_address), 0, KNXWRITE, value]))
                else:
                    self.logger.warn("write: not a valid knx type")
                return True
            except Exception as e:
                self.logger.warn("unable to send knx messages. restarting connection")
                self.loadConnections(self.knxLocation, self.knxPort)

    ########################################
    # ACTION CALLBACKS
    ########################################

    def actionControlDimmerRelay(self, action, dev):
        ###### TURN ON ######
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            if dev.deviceTypeId == "knxDimmer":
                self.writeToKNX("5.x", dev.pluginProps["set_absdim"], 255)
            else:
                self.writeToKNX("1.x", dev.pluginProps["set_onoff"], 1)
            dev.updateStateOnServer("onOffState", True)
        ###### TURN OFF ######
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            self.writeToKNX("1.x", dev.pluginProps["set_onoff"], 0)
            dev.updateStateOnServer("onOffState", False)
        ###### TOGGLE ######
        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            newOnState = not dev.onState
            value = 1 # on
            if newOnState == False:
                value = 0
            self.writeToKNX("1.x", dev.pluginProps["set_onoff"], value)
            dev.updateStateOnServer("onOffState", newOnState)
        ###### SET BRIGHTNESS ######
        elif action.deviceAction == indigo.kDeviceAction.SetBrightness:
            self.writeToKNX("5.x", dev.pluginProps["set_absdim"], int(float(action.actionValue) * 2.55))
            if action.actionValue == 0:
                dev.updateStateOnServer("onOffState", False)
            else:
                dev.updateStateOnServer("onOffState", True)
                dev.updateStateOnServer("brightnessLevel", action.actionValue)
        ###### BRIGHTEN BY ######
        # elif action.deviceAction == indigo.kDeviceAction.BrightenBy:
        #     self.logger.info("BrightenBy - Relative")
        # ###### DIM BY ######
        # elif action.deviceAction == indigo.kDeviceAction.DimBy:
        #     self.logger.info("DimBy - Relative")
        ###### STATUS REQUEST ######
        # elif action.deviceAction == indigo.kDeviceAction.RequestStatus:
        #   self.logger.info("RequestStatus")
        else:
            self.logger.warn("knx action \"%s\" not currently supported" % (action.deviceAction))

    def actionControlThermostat(self, action, dev):
        if action.thermostatAction == indigo.kThermostatAction.SetHeatSetpoint:
            self.logger.info("SetHeatSetpoint")
        elif action.thermostatAction == indigo.kThermostatAction.DecreaseHeatSetpoint:
            self.logger.info("DecreaseHeatSetpoint")
        elif action.thermostatAction == indigo.kThermostatAction.IncreaseHeatSetpoint:
            self.logger.info("IncreaseHeatSetpoint")
        elif action.thermostatAction == indigo.kThermostatAction.SetHvacMode:
            self.logger.info("SetHvacMode")
        elif action.thermostatAction == indigo.kThermostatAction.RequestStatusAll:
            self.logger.info("RequestStatusAll")
        elif action.thermostatAction == indigo.kThermostatAction.RequestMode:
            self.logger.info("RequestMode")
        elif action.thermostatAction == indigo.kThermostatAction.DecreaseCoolSetpoint:
            self.logger.info("DecreaseCoolSetpoint")
        elif action.thermostatAction == indigo.kThermostatAction.IncreaseCoolSetpoint:
            self.logger.info("IncreaseCoolSetpoint")
        elif action.thermostatAction == indigo.kThermostatAction.SetCoolSetpoint:
            self.logger.info("SetCoolSetpoint")
        else:
            self.logger.warn("knx action \"%s\" not currently supported" % (action.thermostatAction))

    ########################################
    # UI FUNCTIONS
    ########################################
    
    def generateGroupAddressList(self, filter="", valuesDict=None, typeId="", targetId=0):
        returnArray = []
        for key, value in sorted(self.groupAddresses.iteritems(), key=lambda (k,v): (v,k)):
            returnArray.append((key, value["list_string"]))
        return returnArray
    
    ########################################
    # MISC UTILITY FUNCTIONS
    # Shamelessly borrowed from https://github.com/mfussenegger/knx
    ########################################
    
    def encode_ga(self, addr):
        """ converts a group address to an integer
        >>> encode_ga('0/1/14')
        270
        >>> encode_ga(GroupAddress(0, 1, 14))
        270
        See also: http://www.openremote.org/display/knowledge/KNX+Group+Address
        """
        def conv(main, middle, sub):
            return (int(main) << 11) + (int(middle) << 8) + int(sub)

        parts = addr.split('/')
        if len(parts) == 3:
            return conv(parts[0], parts[1], parts[2])
    
    def decode_ga(self, ga):
        """ decodes a group address back into its human readable string representation
        >>> decode_ga(270)
        '0/1/14'
        """
        if not isinstance(ga, int):
            ga = struct.unpack('>H', ga)[0]
        return '{}/{}/{}'.format((ga >> 11) & 0x1f, (ga >> 8) & 0x07, (ga) & 0xff)
        
    def decode_ia(self, ia):
        """ decodes an individual address into its human readable string representation
        >>> decode_ia(4606)
        '1.1.254'
        See also: http://www.openremote.org/display/knowledge/KNX+Individual+Address
        """
        if not isinstance(ia, int):
            ia = struct.unpack('>H', ia)[0]
        return '{}/{}/{}'.format((ia >> 12) & 0x1f, (ia >> 8) & 0x07, (ia) & 0xff)
        
    def encode_data(self, fmt, data):
        """ encode the data using struct.pack
        >>> encoded = encode_data('HHB', (27, 1, 0))
        = ==================
        >   big endian
        H   unsigned integer
        B   unsigned char
        = ==================
        """
        ret = struct.pack('>' + fmt, *data)
        if len(ret) < 2 or len(ret) > 0xffff:
            raise ValueError('(encoded) data length needs to be between 2 and 65536')
        # prepend data length
        return struct.pack('>H', len(ret)) + ret
        
    def decode_message(self, buf):
        """ decodes a binary telegram in the format:
            2 byte: src
            2 byte: dst
            X byte: data
        Returns a Telegram namedtuple.
        For read requests the value is -1
        If the data had only 1 bytes the value is either 0 or 1
        In case there was more than 1 byte the value will contain the raw data as
        bytestring.
        >>> _decode(bytearray([0x11, 0xFE, 0x00, 0x07, 0x00, 0x83]))
        Telegram(src='1.1.254', dst='0/0/7', value=3)
        >>> _decode(bytearray([0x11, 0x08, 0x00, 0x14, 0x00, 0x81]))
        Telegram(src='1.1.8', dst='0/0/20', value=1)
        """
        # need to strip everything from the buffer before, and including '
        buf = buf.split('\'', 1)[-1]
        src = self.decode_ia(buf[0] << 8 | buf[1])
        dst = self.decode_ga(buf[2] << 8 | buf[3])
        flg = buf[5] & 0xC0
        data = buf[5:]
        if flg == KNXREAD:
            value = -1
        elif len(data) == 1:
            value = data[0] & 0x3F
        elif len(data) == 2:
            value = struct.unpack(">B", data[1:2])[0]
        elif len(data) == 3:
            try:
                tmp = data[1] * 256 + data[2]
                sign = tmp >> 15
                exponent = (tmp >> 11) & 0x0f
                argument = float(tmp & 0x7ff)
                if sign == 1:
                    argument = -2048 + argument
                value = argument * pow(2, exponent) / 100
            except Exception as e:
                self.logger.warn(e)
        else:
            self.logger.warn("cannot handle this data type: "+str(len(data)))
            value = 0
        if self.knxDebug:
            self.logger.info("from: "+str(src)+" to: "+str(dst)+" value: "+str(value))
        return (src, dst, value)