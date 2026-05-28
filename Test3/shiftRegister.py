#!/usr/bin/python

#LATCH = 5 # Pin 12 Latch clock
#CLK = 6 # Pin 11 shift clock
#dataBit = 4 # Pin 14 A

from time import sleep

        
class ShiftRegister(object):

    LATCH = 5   # Pin 12 Latch clock
    CLK = 6     # Pin 11 shift clock
    dataBit = 4 # Pin 14 A

    def __init__(self, LATCH=5, CLK=6, dataBit=4, GPIO=None):
        
        if not GPIO:
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False)
        self.GPIO = GPIO
        
        self.LATCH = LATCH
        self.CLK = CLK
        self.dataBit = dataBit

        self.GPIO.setmode(GPIO.BCM)
        self.GPIO.setup(self.LATCH, GPIO.OUT)
        self.GPIO.setup(self.CLK, GPIO.OUT)
        self.GPIO.setup(self.dataBit, GPIO.OUT)

       
    def pulseCLK(self):
        self.GPIO.output(self.CLK, 1)
        # time.sleep(.01) 
        self.GPIO.output(self.CLK, 0)
        return

    def serLatch(self):
        self.GPIO.output(self.LATCH, 1)
       # time.sleep(.01)
        self.GPIO.output(self.LATCH, 0)
        return


    # MSB out first!
    def ssrWrite(self, value1 = 0, value2 = 0, value3 = 0):
    
        #global valueShiftReg3Hist
        #global valueShiftReg2Hist
        #global valueShiftReg1Hist
    
        temp = 0
        #valueShiftReg3Hist = value1 & valueShiftReg3Hist
        for  x in range(0,8):
            temp = value1 & 0x80        # 1000 0000
        
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value1 = value1 << 0x01     # shift left
        
        temp = 0
        #valueShiftReg2Hist = value2 & valueShiftReg2Hist
        for  x in range(0,8):
            temp = value2 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value2 = value2 << 0x01     # shift left

        temp = 0
        #valueShiftReg3Hist = value3 & valueShiftReg1Hist
        for  x in range(0,8):
            temp = value3 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value3 = value3 << 0x01     # shift left
        
        self.serLatch() # output byte
        return 


    # MSB out first!
    def ssrWrite_4(self, value1 = 0, value2 = 0, value3 = 0, value4 = 0):
    
        # SR 1
        temp = 0
        for  x in range(0,8):
            temp = value1 & 0x80        # 1000 0000
        
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value1 = value1 << 0x01     # shift left

        # SR 2    
        temp = 0
        for  x in range(0,8):
            temp = value2 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value2 = value2 << 0x01     # shift left

        # SR 3
        temp = 0
        for  x in range(0,8):
            temp = value3 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value3 = value3 << 0x01     # shift left

        # SR 4
        temp = 0
        for  x in range(0,8):
            temp = value4 & 0x80        # 1000 0000
        
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value4 = value4 << 0x01     # shift left
        
        self.serLatch() # output byte
        return                  


    # MSB out first!
    def ssrWrite_8(self, value1 = 0b00000000, value2 = 0b00000000, value3 = 0b00000000, value4 = 0b00000000, value5 = 0b00000000, value6 = 0b00000000, value7 = 0b00000000, value8 = 0b00000000):
   
        # SR 1
        temp = 0
        for  x in range(0,8):
            temp = value1 & 0x80        # 1000 0000
        
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value1 = value1 << 0x01     # shift left

        # SR 2    
        temp = 0
        for  x in range(0,8):
            temp = value2 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value2 = value2 << 0x01     # shift left

        # SR 3
        temp = 0
        for  x in range(0,8):
            temp = value3 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value3 = value3 << 0x01     # shift left

        # SR 4
        temp = 0
        for  x in range(0,8):
            temp = value4 & 0x80        # 1000 0000
        
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value4 = value4 << 0x01     # shift left
        
        # SR 5
        temp = 0
        for  x in range(0,8):
            temp = value5 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value5 = value5 << 0x01     # shift left

        # SR 6
        temp = 0
        for  x in range(0,8):
            temp = value6 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value6 = value6 << 0x01     # shift left

        # SR 7
        temp = 0
        for  x in range(0,8):
            temp = value7 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value7 = value7 << 0x01     # shift left

        # SR 8
        temp = 0
        for  x in range(0,8):
            temp = value8 & 0x80
            if temp == 0x80:
               self.GPIO.output(self.dataBit, 1)  # data bit HIGH
            else:
               self.GPIO.output(self.dataBit, 0)  # data bit LOW
            self.pulseCLK()        
            value8 = value8 << 0x01     # shift left                 
        
        self.serLatch() # output byte
        #return                  


    def clear(self):
        self.delayMicroseconds(300)  # 3000 microsecond sleep, clearing the display takes a long time

    def delayMicroseconds(self, microseconds):
        seconds = microseconds / float(1000000)  # divide microseconds by 1 million for seconds
        sleep(seconds)



if __name__ == '__main__':
    SR = ShiftRegister()
    #SR.ssrWrite_8(0b00000000, 0b00000000, 0b00000000, 0b00000000, 0b00000000, 0b00000000, 0b00000000, 0b00000000)
    SR.ssrWrite_4( 0b00000001, 0b00000001, 0b00000001, 0b00000001 )
    

    
