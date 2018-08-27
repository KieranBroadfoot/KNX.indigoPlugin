KNX.indigoPlugin
==================

A [KNX](http://www.knx.org) plugin for [Indigo Domotics](http://www.indigodomo.com)

Supported Devices
-----------------

The following device types are currently supported:

* Relay (1.001)
* Dimmer (5.001 and 1.001)
* PIR (1.00X)
* NO/NC Sensor (1.00X)
* Light Sensor (9.004)
* Temperature Sensor (9.001)

Sensors are set to only receive status updates from the KNX network

Network Configuration
---------------------

The goal is for this plugin to support two different types of connectivity to KNX.  In its first iteration the only support interface is via a [knxd](https://github.com/knxd/knxd) installation but I am hoping to add support for KNX IP enabled interfaces via tunneling.  The simplest method is to setup knxd on a raspberry pi or VM running Debian.  The knxd daemon can be configured to tunnel to an KNX IP interface (such as the Weinzierl 762) or direct connect to a KNX USB interface.

Group Addresses
---------------

Whilst Group Addresses can be manually entered into the device configuration it is also possible for the plugin to parse your ETS file (v4 or 5) to extract group addresses.  Copy your ETS file to your Mac and enter the path in the plugin preferences pane.  

Tested Equipment
----------------

This plugin has limited testing on a prototype board using Weinzierl and Jung equipment.  Sensors were provided via an Arduino and Siemens [Bus Coupler](https://mall.industry.siemens.com/mall/en/ww/Catalog/Product/5WG1117-2AB12).  See [Thorsten's Bitbucket](https://bitbucket.org/thorstengehrig/arduino-tpuart-knx-user-forum) for more details.

Open Source
-----------

This plugin uses helper functions from [https://github.com/mfussenegger/knx](https://github.com/mfussenegger/knx) 
