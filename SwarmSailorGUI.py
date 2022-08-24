"""
Python3 PyQt5 GUI for SWARM Sailor

Written by: Jackson Wiebe
Based from: Paul Clark, SparkFun
Date: 14-Aug-2022

To install PyQt5:

  pip install PyQt5

or

  pip3 install PyQt5

To run:
Add the enviroment:
    python3 -m venv venv

Run
    Python Swarm_M138_GUI.py

MIT license

Please see the LICENSE.md for more details

TODO:
-Impliment multipart messges
-Impliment AEC compression

"""

from typing import Iterator, Tuple
from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QProcess, QSettings, QTimer, Qt, QIODevice, pyqtSlot
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
from datetime import datetime
import sys
import os.path
import logging
import math
import re
import random

# Constants
GUIVERSION = 'v1.0.0'
APPNAME = "SwamSailorGUI"
ORGNAME = "SwamSailor"
LOGFILENAME = 'SwarmSailor.log'
GRIBFOLDER = 'GRIBs'
MSGLOG = 'MessageHistory.log'

# SWARM Constants
APPID_OUTGOING_GPS_PING = 37400
APPID_OUTGOING_MESSAGE = 37500
APPID_OUTGOING_MESSAGE_PART_REQ = 37510
APPID_OUTGOING_GRIBRQ = 37600
APPID_OUTGOING_GRIBRQ_PART_REQ = 37610
APPID_INCOMING_MESSAGE = 37550
APPID_INCOMING_MESSAGE_PART_REQ = 37560
APPID_INCOMING_GRIB = 37700

# Settings
SETTING_PORT_NAME = 'COM1'

# Setup global log
logging.basicConfig(filename=LOGFILENAME,
                    filemode='w',
                    format='%(asctime)s %(name)s \t %(levelname)s \t %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

logging.info("SwarmSailor Log Started")


def gen_serial_ports() -> Iterator[Tuple[str, str, str]]:
    """Return all available serial ports."""
    ports = QSerialPortInfo.availablePorts()
    return ((p.description(), p.portName(), p.systemLocation()) for p in ports)


class system_status:
    comm_status = "Disconnected"
    RSSI = 0
    tx_waiting = 0
    rx_waiting = 0

    def print_nice(self):
        return_string = self.comm_status + "\n"
        return_string += "RSSI: " + str(self.RSSI)
        if (self.RSSI >= -90):
            return_string += " Bad"
        elif (self.RSSI <= -93):
            return_string += " Marginal"
        elif (self.RSSI <= -97):
            return_string += " OK"
        elif (self.RSSI <= -100):
            return_string += " Good"
        elif (self.RSSI <= -105):
            return_string += " Great"

        if (self.tx_waiting != 0):
            return_string += "\n" + "TX Waiting: " + str(self.tx_waiting)
        if (self.rx_waiting != 0):
            return_string += "\n" + "RX Waiting: " + str(self.rx_waiting)
        return return_string


class Geolocation:
    latitude = 0.0
    longitude = 0.0
    altitude = 0
    course = 0
    speed = 0

    def print_swarm(self):
        return str(self.latitude) + ", " + str(self.longitude)

    def print_nice(self):
        return str(self.latitude) + ", " + str(self.longitude) + "\n" + str(self.altitude) + "m\n" + str(self.speed) + "kph, " + str(self.course).zfill(3) + "°"


class SwarmMessage:
    appid = ''
    rssi = ''
    snr = ''
    fdev = ''
    data = ''

    def __init__(self, buildabear):
        regex = '\s|,|\*|='
        array = re.split(regex, buildabear)
        self.appid = array[0]
        self.rssi = array[1]
        self.snr = array[2]
        self.fdev = array[3]
        self.data = array[4]

    def print_nice(self):
        return "New Message " + self.data

    def write_to_disk(self):
        current_time = datetime.now().strftime("%c")
        if (self.appid == APPID_INCOMING_GRIB):
            print_file = open(GRIBFOLDER + "/" + current_time + self.data[0:6] + ".grb2", 'w')
            print(self.print_nice(), file=print_file)
            print_file.close()
        else:  # Write to message log
            print_file = open(MSGLOG, 'a')
            print(current_time + " < " + self.print_nice(), file=print_file)
            print_file.close()


# Global variable
current_geolocation = Geolocation()
current_system_status = system_status()


class Ui(QtWidgets.QMainWindow):
    def __init__(self):
        super(Ui, self).__init__()
        uic.loadUi('dialog.ui', self)

        # Timers
        self.timer1s = QTimer()
        self.timer1s.timeout.connect(self.timer1s_exec)
        self.timer1s.start(1000)

        self.timer5s = QTimer()
        self.timer5s.timeout.connect(self.timer5s_exec)
        self.timer5s.start(5000)

        self.timerTracker = QTimer()
        self.timerTracker.timeout.connect(self.timer_tracker_exec)

        # Ui Tweaks
        self.setWindowTitle(
            'Swarm M138 GUI - by SwarmSailor - ' + GUIVERSION)  # Update Title
        # self.findChild(QtWidgets.QWidget, 'advancedSection').hide() #Hide Advanced Section
        self.update_com_ports()  # get COMS

        # Text boxes
        self.findChild(QtWidgets.QPlainTextEdit, 'Messages_Display').setReadOnly(True)  # Make these text edit windows read-only
        self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').setReadOnly(True)  # Make these text edit windows read-only

        # Buttons
        self.findChild(QtWidgets.QPushButton, 'Button_Advanced').clicked.connect(self.Button_Advanced_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Close_Port').clicked.connect(self.Button_Close_Port_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Get_GRIB').clicked.connect(self.Button_Get_GRIB_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Open_Port').clicked.connect(self.Button_Open_Port_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Refresh_PORT').clicked.connect(self.Button_Refresh_PORT_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Send_Message').clicked.connect(self.Button_Send_Message_click)
        self.findChild(QtWidgets.QPushButton, 'Button_GPS_Tracker').clicked.connect(self.Button_GPS_Tracker_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Send_Ping').clicked.connect(self.Button_Send_Ping_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Firmware').clicked.connect(self.Button_Firmware_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Geospatial').clicked.connect(self.Button_Geospatial_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Empty_TX').clicked.connect(self.Button_Empty_TX_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Restart').clicked.connect(self.Button_Restart_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Serial_Monitor_Send').clicked.connect(self.Button_Serial_Monitor_Send_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Serial_Terminal_Clear').clicked.connect(self.Button_Serial_Terminal_Clear_click)
        self.findChild(QtWidgets.QPushButton, 'Button_DeviceID').clicked.connect(self.Button_DeviceID_click)
        self.findChild(QtWidgets.QPushButton, 'Button_Mailbox').clicked.connect(self.Mailbox_check)

        self.loadHistory()

        self.show()

    def Button_Advanced_click(self):
        self.widget = self.findChild(QtWidgets.QWidget, 'advancedSection')
        if self.widget.isVisible():
            self.widget.hide()
        else:
            self.widget.show()

    def printer(self, somedata):
        print(somedata)

    def Button_Open_Port_click(self):
        port_available = False
        for desc, name, sys in gen_serial_ports():
            try:
                if (sys == self.currentPort()):
                    port_available = True
            except:
                pass

        if (port_available == False):
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText("Error: Port Not Available!")
            current_system_status.comm_status = "Error: Port Not Available!"
            try:
                self.ser.close()
            except:
                pass
            return

        try:
            if self.ser.isOpen():
                port_available = True
            else:
                port_available = False
        except:
            port_available = False

        if (port_available == True):
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText("Port Is Already Open!")
            return

        try:
            self.ser = QSerialPort()
            self.ser.setPortName(self.currentPort())
            self.ser.setBaudRate(QSerialPort.Baud115200)
            self.ser.open(QIODevice.ReadWrite)
        except Exception as err:
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText("Error: Failed to Open Port {}".format(err))
            current_system_status.comm_status = "Error: Failed to Open Port"
            try:
                self.ser.close()
            except:
                pass
            return

        self.save_settings()

        self.ser.readyRead.connect(self.receive)  # Connect the receiver

        self.send_Serial_Command('CS')     # Configuration Settings
        self.send_Serial_Command('FV')     # Firmware Version Read
        self.send_Serial_Command('GN 2')   # Enable GNSS data
        self.send_Serial_Command('RT 2')   # Enable RSSI

        self.Mailbox_check()

        self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText("Port is now open")
        current_system_status.comm_status = "Comm OK"

    def Button_Close_Port_click(self):
        """Close the port"""
        port_available = False
        for desc, name, sys in gen_serial_ports():
            try:
                if (sys == self.currentPort()):
                    port_available = True
            except:
                pass

        if (port_available == False):
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText(
                "Error: Port No Longer Available!")
            current_system_status.comm_status = "Error: Port Not Available!"
            try:
                self.ser.close()
            except:
                pass
            return

        try:
            if self.ser.isOpen():
                port_available = True
            else:
                port_available = False
        except:
            port_available = False

        if (port_available == False):
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText(
                "Port Is Already Closed!")
            try:
                self.ser.close()
            except:
                pass
            return

        try:
            self.ser.close()
        except:
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText(
                "Error: Could Not Close The Port!")
            return

        self.save_settings()
        self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText(
            "Port is now closed")

    def Button_Refresh_PORT_click(self):
        try:
            self.ser.close()
        except:
            pass
        current_system_status.comm_status = "Disconnected"
        self.update_com_ports()

    def Button_Get_GRIB_click(self):
        dialog = QDialogGRIB()
        dialog.exec_()
        self.sendTDSwarm(APPID_OUTGOING_GRIBRQ, dialog.returnString())

    def Button_Send_Message_click(self):
        dialog = QDialogMessage()
        dialog.exec_()
        message_outgoing = str(random.randint(10, 99)) + str(1) + str(1) + dialog.returnString()
        self.sendTDSwarm(APPID_OUTGOING_MESSAGE, message_outgoing)

    def Button_GPS_Tracker_click(self):
        if (self.tracker_active):
            self.tracker_active = False
            self.timerTracker.stop()  # Stop broadcasting
            self.findChild(QtWidgets.QPushButton, 'Button_GPS_Tracker').setStyleSheet('QPushButton {}')
        else:
            self.tracker_active = True
            self.timerTracker.start(1000 * 60 * 60)  # Send every hour
            self.findChild(QtWidgets.QPushButton, 'Button_GPS_Tracker').setStyleSheet('QPushButton {background-color: #52BE80;}')
    tracker_active = False

    def Button_Send_Ping_click(self):
        self.timer_tracker_exec()

    def Button_Serial_Monitor_Send_click(self):
        self.send_Serial_Command(self.findChild(
            QtWidgets.QLineEdit, 'Serial_Monitor_SendLine').text())
        self.findChild(QtWidgets.QLineEdit, 'Serial_Monitor_SendLine').clear()

    def Button_DeviceID_click(self):
        self.send_Serial_Command('CS')

    def Button_Firmware_click(self):
        self.send_Serial_Command('FV')

    def Button_Empty_TX_click(self):
        self.send_Serial_Command('MT D=U')

    def Button_Geospatial_click(self):
        if self.geospatial_active:
            self.send_Serial_Command('GN 0')
            self.geospatial_active = 0
        else:
            self.send_Serial_Command('GN 1')
            self.geospatial_active = 1
    geospatial_active = 1

    def Button_Restart_click(self):
        self.send_Serial_Command('RS')

    def Button_Serial_Terminal_Clear_click(self):
        self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').clear()

    def Mailbox_check(self):
        self.send_Serial_Command("MM L=U")  # request count of unread
        self.send_Serial_Command("MT C=U")  # request count of unsent

    def send_Serial_Command(self, message, printthis=True) -> None:
        port_available = False
        for desc, name, sys in gen_serial_ports():
            try:
                if (sys == self.currentPort()):
                    port_available = True
            except:
                pass

        if (port_available == False):
            current_system_status.comm_status = "Error: Port Not Available!"
            try:
                self.ser.close()
            except:
                pass
            return

        if (message == ''):
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText("Warning: Nothing To Do! Message Is Empty!")
            return

        self.ser.write(bytes('$', 'utf-8'))  # Send the $
        self.ser.write(bytes(message, 'utf-8'))  # Send the message
        self.ser.write(bytes('*', 'utf-8'))  # Send the *
        self.ser.write(str.format(
            '{:02X}', self.chksum_nmea(message)).encode('utf-8'))
        self.ser.write(bytes('\n', 'utf-8'))

        if (printthis):
            print_msg = datetime.now().strftime("%H:%M:%S")
            print_msg += " > $"
            print_msg += message
            print_msg += "*"
            print_msg += str.format('{:02X}', self.chksum_nmea(message)).encode('utf-8').decode('utf-8')
            self.findChild(QtWidgets.QPlainTextEdit,     'Serial_Monitor_Display').appendPlainText(print_msg)

    def sendTDSwarm(self, appid, message):
        packet = "TD AI=" + str(appid) + ",\"" + message + "\""
        self.send_Serial_Command(packet)

    @pyqtSlot()
    def receive(self) -> None:
        try:
            while self.ser.canReadLine():
                text = self.ser.readLine().data().decode()
                current_time = datetime.now().strftime("%H:%M:%S")
                regex = '\s|,|\*|='
                match text[0:3]:
                    case "$RT":
                        array = re.split(regex, text)
                        current_system_status.RSSI = int(array[2])
                    case '$MT':
                        array = re.split(regex, text)
                        current_system_status.tx_waiting = array[1]
                    case '$MM':
                        substring_ignore_list = [
                            "DBX_NOMORE", "CMD_BADPARAMVALUE", "MM OK*24", "MM 0*10"]
                        if any(substring in text for substring in substring_ignore_list):
                            break
                        else:
                            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText(
                                current_time + " < " + text.strip())
                            array = re.split(regex, text)
                            self.getUnreadMessages(array[1:])
                    case '$GN':
                        array = re.split(regex, text)
                        current_geolocation.latitude = float(array[1])
                        current_geolocation.longitude = float(array[2])
                        current_geolocation.altitude = int(array[3])
                        current_geolocation.course = int(array[4])
                        current_geolocation.speed = int(array[5])
                    case _:  # wildcard
                        self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText(
                            current_time + " < " + text.strip())
        except:
            pass

    def getUnreadMessages(self, list_messages):
        logging.info("Incoming Data: " + list_messages)
        regex = '\s|,|\*|='
        array = re.split(regex, list_messages)
        for x in array:
            self.findChild(QtWidgets.QPlainTextEdit, 'Serial_Monitor_Display').appendPlainText("Array Item: " + x)
            self.send_Serial_Command("MM R=" + x)
            self.ser.waitForBytesWritten()
            new_message = self.ser.readLine().data().decode()
            incoming_message = SwarmMessage(new_message)
            current_time = datetime.now().strftime("%H:%M:%S")
            if (incoming_message.appID == str(APPID_INCOMING_MESSAGE)):
                self.findChild(QtWidgets.QPlainTextEdit, 'Messages_Display').appendPlainText(current_time + " < " + incoming_message.print_nice())
            elif (incoming_message.appID == str(APPID_INCOMING_GRIB)):
                self.findChild(QtWidgets.QPlainTextEdit, 'Messages_Display').appendPlainText(current_time + " < " + "GRIB Recieved")
            else:
                self.findChild(QtWidgets.QPlainTextEdit, 'Messages_Display').appendPlainText(current_time + " < " + "Uknown Message Receieved")
            incoming_message.write_to_disk()

    def currentLocation(self):
        return (self.current_geolocation)

    def chksum_nmea(self, sentence):
        """Calculate the NMEA checksum"""
        # Initializing our first XOR value
        csum = 0
        # For each char in chksumdata, XOR against the previous XOR'd char.
        # The final XOR of the last char will be our  checksum
        for c in sentence:
            csum ^= ord(c)
        return csum

    def timer1s_exec(self) -> None:
        # Check if port is still ok
        port_available = False
        for desc, name, sys in gen_serial_ports():
            try:
                if (sys == self.currentPort()):
                    port_available = True
            except:
                pass

        if (port_available == False):
            current_system_status.comm_status = "Error: Port No Longer Available!"
            try:
                self.ser.close()
            except:
                pass
        # Do GUI Updates
        self.findChild(QtWidgets.QLabel, 'data_GNSS').setText(current_geolocation.print_nice())
        self.findChild(QtWidgets.QLabel, 'data_Status').setText(current_system_status.print_nice())
        if (self.tracker_active):
            self.findChild(QtWidgets.QPushButton, 'Button_GPS_Tracker').setText(
                'GPS Tracker ' + str(round(self.timerTracker.remainingTime() / 1000 / 60, 1)) + " min")
        else:
            self.findChild(QtWidgets.QPushButton, 'Button_GPS_Tracker').setText('GPS Tracker Off')

    def timer5s_exec(self):
        # Check for Mail
        self.send_Serial_Command("MM L=U", False)  # request list of unread
        self.send_Serial_Command("MT C=U", False)  # request count of unsent

    def timer_tracker_exec(self):
        self.sendTDSwarm(APPID_OUTGOING_GPS_PING, current_geolocation.print_swarm())

    def update_com_ports(self) -> None:
        self.findChild(QtWidgets.QComboBox, 'comboBox_PORT').clear()
        for desc, name, sys in gen_serial_ports():
            longname = desc + " (" + name + ")"
            self.findChild(QtWidgets.QComboBox,
                           'comboBox_PORT').addItem(longname, sys)

    def currentPort(self) -> str:
        return self.findChild(QtWidgets.QComboBox, 'comboBox_PORT').currentData()

    def loadHistory(self):
        # load Settings file
        self.settings = QSettings(APPNAME, ORGNAME)

        port_name = self.settings.value(SETTING_PORT_NAME)
        if port_name is not None:
            index = self.findChild(QtWidgets.QComboBox,
                                   'comboBox_PORT').findData(port_name)
            if index > -1:
                self.findChild(QtWidgets.QComboBox,
                               'comboBox_PORT').setCurrentIndex(index)

        # look for the appropriate directory
        if not os.path.exists(GRIBFOLDER):
            os.makedirs(GRIBFOLDER)
        try:
            if os.path.exists(MSGLOG):
                # load log into terminal
                f = open(MSGLOG, "r")
                for line in f:
                    self.findChild(QtWidgets.QPlainTextEdit, 'Messages_Display').appendPlainText(line.strip())
            else:
                # make new log file
                f = open(MSGLOG, "w")
            f.close()
        except:
            logging.error("Unable to open" + MSGLOG)

    def save_settings(self) -> None:
        logging.info("Saving Settings")
        self.settings = QSettings(APPNAME, ORGNAME)
        self.settings.setValue(SETTING_PORT_NAME, self.currentPort())
        self.settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle Close event of the Program."""
        try:
            self.save_settings()
        except:
            pass

        try:
            self.ser.close()
        except:
            pass

        try:
            self.f.close()
        except:
            pass

        event.accept()


class QDialogMessage(QtWidgets.QDialog):
    return_message = ''

    def __init__(self):
        super(QDialogMessage, self).__init__()
        uic.loadUi('message.ui', self)
        self.findChild(QtWidgets.QLineEdit, 'lineEdit_TO').textChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QLineEdit, 'lineEdit_Subject').textChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QPlainTextEdit, 'plainTextEdit_Message').textChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QPushButton, 'Button_Send').clicked.connect(self.done)

    def calculateMessage(self):
        self.return_message = "T:"
        self.return_message += self.findChild(QtWidgets.QLineEdit, 'lineEdit_TO').text()
        self.return_message += "S:"
        self.return_message += self.findChild(QtWidgets.QLineEdit, 'lineEdit_Subject').text()
        self.return_message += "M"
        self.return_message += self.findChild(QtWidgets.QPlainTextEdit, 'plainTextEdit_Message').toPlainText()
        self.findChild(QtWidgets.QLabel, 'label_Size_Calc').setText(str(len(self.return_message)) +
                                                                    " Chars (" + str(math.ceil(len(self.return_message)/192)) + " packets)")

    def returnString(self):
        return self.return_message


class QDialogGRIB(QtWidgets.QDialog):
    def __init__(self):
        super(QDialogGRIB, self).__init__()
        uic.loadUi('gribReq.ui', self)
        self.findChild(QtWidgets.QPushButton, 'Button_Get_Location').clicked.connect(self.Button_Get_Location_Click)
        self.findChild(QtWidgets.QPushButton, 'Button_Send_GRIB').clicked.connect(self.done)
        self.findChild(QtWidgets.QComboBox, 'comboBox_Model').currentTextChanged.connect(self.change_model)
        self.change_model(self.findChild(QtWidgets.QComboBox, 'comboBox_Model').currentText())  # Set Checkboxs to Default
        # Connect Change Listeners
        self.findChild(QtWidgets.QComboBox, 'comboBox_Model').currentIndexChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QComboBox, 'comboBox_Res').currentIndexChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QComboBox, 'comboBox_Range').currentIndexChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QComboBox, 'comboBox_Interval').currentIndexChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Lat_Max').valueChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Lat_Min').valueChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Long_Min').valueChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Long_Max').valueChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_AirT').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_CAPE').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Cloud').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Pressure').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wave').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wind').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wing').stateChanged.connect(self.calculateMessage)
        self.findChild(QtWidgets.QLineEdit, 'lineEdit_Request').textChanged.connect(self.calc_size)
        self.calculateMessage()

    def calculateMessage(self):
        # Example built around Saildocs send GFS:57N,44N,133W,113W|2.0,2.0|0,6,12..48|= WIND,PRESS
        # Model
        return_message = self.findChild(
            QtWidgets.QComboBox, 'comboBox_Model').currentText() + ":"
        # GPS Range
        return_message += str(self.findChild(QtWidgets.QSpinBox, 'spinBox_Lat_Max').value()) + ","
        return_message += str(self.findChild(QtWidgets.QSpinBox, 'spinBox_Lat_Min').value()) + ","
        return_message += str(self.findChild(QtWidgets.QSpinBox, 'spinBox_Long_Min').value()) + ","
        return_message += str(self.findChild(QtWidgets.QSpinBox, 'spinBox_Long_Max').value()) + "|"
        # Resolution
        return_message += str(self.findChild(QtWidgets.QComboBox, 'comboBox_Res').currentText()) + "|"
        #Interval and Duration
        return_message += str(self.findChild(QtWidgets.QComboBox, 'comboBox_Interval').currentText()) + ","
        return_message += str(self.findChild(QtWidgets.QComboBox, 'comboBox_Range').currentText()) + "|"
        # Data Types
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').checkState():
            return_message += "CUR,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_AirT').checkState():
            return_message += "AIRTMP,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_CAPE').checkState():
            return_message += "CAPE,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_Cloud').checkState():
            return_message += "TCDC,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_Pressure').checkState():
            return_message += "PRESS,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_Wave').checkState():
            return_message += "HTSGW,WVPER,WVDIR,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_Wind').checkState():
            return_message += "WIND,"
        if self.findChild(QtWidgets.QCheckBox, 'checkBox_Wing').checkState():
            return_message += "GUST,"
        self.findChild(QtWidgets.QLabel, 'data_Size_estimate').setText(str(math.ceil(len(return_message))) + " Chars (Max 192)")

        self.findChild(QtWidgets.QLineEdit, 'lineEdit_Request').setText(return_message[:len(return_message)-1])

    def calc_size(self):
        self.findChild(QtWidgets.QLabel, 'data_Size_estimate').setText(str(math.ceil(len(
            self.findChild(QtWidgets.QLineEdit, 'lineEdit_Request').text()))) + " Chars (Max 192)")

    def returnString(self):
        return self.findChild(QtWidgets.QLineEdit, 'lineEdit_Request').text()

    def Button_Get_Location_Click(self):
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Lat_Max').setValue(round(current_geolocation.latitude))
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Lat_Min').setValue(round(current_geolocation.latitude))
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Long_Max').setValue(round(current_geolocation.longitude))
        self.findChild(QtWidgets.QSpinBox, 'spinBox_Long_Min').setValue(round(current_geolocation.longitude))

    def change_model(self, new_model):
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_AirT').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_CAPE').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Cloud').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Pressure').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wave').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wind').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wing').setCheckState(Qt.Unchecked)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_AirT').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_CAPE').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Cloud').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Pressure').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wave').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wind').setEnabled(True)
        self.findChild(QtWidgets.QCheckBox, 'checkBox_Wing').setEnabled(True)

        self.findChild(QtWidgets.QComboBox, 'comboBox_Range').clear()
        match new_model:
            case 'GFS':
                for x in range(1, 17):
                    self.findChild(QtWidgets.QComboBox, 'comboBox_Range').addItem(str(x))
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Wind').setCheckState(Qt.Checked)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Pressure').setCheckState(Qt.Checked)
            case 'RTOFS':
                for x in range(1, 7):
                    self.findChild(QtWidgets.QComboBox, 'comboBox_Range').addItem(str(x))
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').setCheckState(Qt.Checked)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Current').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_AirT').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_CAPE').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Cloud').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Pressure').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Wave').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Wind').setEnabled(False)
                self.findChild(QtWidgets.QCheckBox, 'checkBox_Wing').setEnabled(False)
            case 'Local':
                return
            case 'ECMWG':
                return
            case 'SPIRE':
                return


app = QtWidgets.QApplication(sys.argv)
window = Ui()
app.exec_()
