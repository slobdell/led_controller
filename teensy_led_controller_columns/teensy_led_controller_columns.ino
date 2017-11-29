/*
 * =====================================================================================
 *
 *       Filename:  current_teensy_sketch.c
 *
 *    Description:  :
 *
 *        Version:  1.0
 *        Created:  05/28/2016 20:18:05
 *       Revision:  none
 *       Compiler:  gcc
 *
 *         Author:  YOUR NAME (),
 *   Organization:
 *
 * ============b=========================================================================
 */



#include <OctoWS2811.h>
#include <stdio.h>

int INDICATOR_PIN = 13;
int BAUD_RATE = 115200;

byte pinstate=LOW;

const int WORD_LENGTH_BYTES = 3;
unsigned char CONTROL_HEADER[WORD_LENGTH_BYTES] = {255, 255, 255};

unsigned char controlIdentificationBuffer[WORD_LENGTH_BYTES] = {0, 0, 0};
unsigned char wordBuffer[WORD_LENGTH_BYTES] = {0, 0, 0};

int controlIdentificationIndex = WORD_LENGTH_BYTES - 1;
int wordIndex = WORD_LENGTH_BYTES - 1;

typedef int serialReadState;

const serialReadState READING_IMAGE = 0;
const serialReadState READING_FRAME_RATE = 1;
const serialReadState READING_WIDTH = 2;
const serialReadState READING_HEIGHT = 3;


serialReadState currentState = READING_IMAGE;

int cursorRow = 0;
int cursorCol = 0;


// likely to change, setting as a reasonable value for expressiveness
short frameWidth = 340;
short frameHeight = 240;
short framesPerSecond = 15;

const int MAX_TEENSY_STRIPS = 8;

DMAMEM int *displayBuffer;
int *drawBuffer;


OctoWS2811 *getLedsInstance(short width_, short height_) {
  int totalLeds = width_ * height_;
  int ledsPerStrip = totalLeds / MAX_TEENSY_STRIPS;
  displayBuffer = (int *)malloc(ledsPerStrip * 6 * sizeof(int));
  drawBuffer = (int *)malloc(ledsPerStrip * 6 * sizeof(int));
  const int CONFIGURATION = WS2811_GRB | WS2811_800kHz; // might need to cange this value
  return new OctoWS2811 (
    ledsPerStrip,
    displayBuffer,
    drawBuffer,
    CONFIGURATION
  );
}

OctoWS2811 *leds = NULL;




char arraysEqual(unsigned char *arr1, unsigned char *arr2, size_t arraySize) {
    unsigned char *cursor1 = arr1;
    unsigned char *cursor2 = arr2;
    for(unsigned int j=0; j<arraySize; j++) {
        if (*cursor1 != *cursor2) {
            return 0;
        }
        cursor1++;
        cursor2++;
    }
    return 1;
}


short shortBytesToShort(unsigned char lsb, unsigned char msb) {
    return ((short) msb) << 8 | lsb;
}


unsigned int bgrToInt(unsigned char r, unsigned char b, unsigned char g) {
  return (
    ((unsigned int)r << 16) |
    ((unsigned int)g << 8) |
    (unsigned int)b
  );
}



void setup() {

    Serial.begin(BAUD_RATE);
    Serial.setTimeout(0);

    pinMode(2, OUTPUT);
    pinMode(3, OUTPUT);
    pinMode(INDICATOR_PIN, OUTPUT);
    digitalWrite(INDICATOR_PIN, HIGH);
}


int BUFFER_SIZE = 512;
char *imageBuffer = (char *) malloc(BUFFER_SIZE);


void loop() {
    int count = 0;
    while (count < BUFFER_SIZE) {
        int bytesRead = Serial.readBytes(imageBuffer + count, BUFFER_SIZE - count);

        if (bytesRead == 0) {
            digitalWrite(3, HIGH);
            while (!Serial.available()); //wait
            digitalWrite(3, LOW);
        }
        count = count + bytesRead;
    }

    // toggle pin 2, so the frequency is kbytes/sec

    // This code existed for some optimization, but it causes flickering, so remove
    /*
    if (pinstate == LOW) {
        digitalWrite(2, HIGH);
        pinstate = HIGH;
    } else {
        digitalWrite(2, LOW);
        pinstate = LOW;
    }
    */


    for(int j=0; j<BUFFER_SIZE; j++){

        /*
        This function has been inlined for performance benefits.  Don't judge
        */
        unsigned char nextByte = (unsigned char)imageBuffer[j];

        // increment Indices
        wordIndex = (wordIndex + 1) % 3;
        controlIdentificationIndex = (controlIdentificationIndex + 1) % 3;

        // set values
        controlIdentificationBuffer[controlIdentificationIndex] = nextByte;
        wordBuffer[wordIndex] = nextByte;

        // take action by current state

        switch(currentState) {
            case READING_IMAGE:

                // search for control header
                if(nextByte == 255 && arraysEqual(controlIdentificationBuffer, CONTROL_HEADER, WORD_LENGTH_BYTES)) {
                    if(leds != NULL) {
                      leds->show();
                    }



                    // prepare next state
                    currentState = READING_FRAME_RATE;
                    wordIndex = WORD_LENGTH_BYTES - 1;

                    cursorRow = 0;
                    cursorCol = 0;
                    continue; // should this be continue instead?
                }
                if(nextByte == 255) {
                  continue; // should this be continue instead?
                }

                if (wordIndex == WORD_LENGTH_BYTES - 1) {

                    //int pixelIndex = frameWidth * cursorRow;
                    int pixelIndex = frameHeight * cursorCol;
                    if(cursorCol % 2 == 0){
                        
                        pixelIndex += (frameHeight - cursorRow);
                    } else {
                        pixelIndex += cursorRow;
                    }
                    if(leds != NULL) {
                        leds->setPixel(
                            pixelIndex,
                            //bgrToInt(60, 0, 0)
                            bgrToInt(wordBuffer[0], wordBuffer[2], wordBuffer[1])
                        );

                    }
                    // increment row and col
                    /*
                    cursorCol++;
                    if (cursorCol >= frameWidth) {
                        cursorCol = 0;
                        cursorRow = (cursorRow + 1) % frameHeight;
                    }
                    */

                    cursorRow++;
                    if (cursorRow >= frameHeight) {
                      cursorRow = 0;
                      cursorCol = (cursorCol + 1) % frameWidth;
                    }
                    //Serial.println(cursorRow);

                }

                break;
            case READING_FRAME_RATE:
                if(wordIndex == WORD_LENGTH_BYTES - 1) {
                    framesPerSecond = shortBytesToShort(wordBuffer[1], wordBuffer[2]);
                    currentState = READING_WIDTH;

                }

                break;
            case READING_WIDTH:
                if(wordIndex == WORD_LENGTH_BYTES - 1) {
                    frameWidth = shortBytesToShort(wordBuffer[1], wordBuffer[2]);
                    currentState = READING_HEIGHT;
                }
                break;
            case READING_HEIGHT:
                if(wordIndex == WORD_LENGTH_BYTES - 1) {
                    frameHeight = shortBytesToShort(wordBuffer[1], wordBuffer[2]);
                    currentState = READING_IMAGE;

                    if(leds == NULL) {
                      leds = getLedsInstance(frameWidth, frameHeight);
                      leds->begin();
                    }
                }
                break;
            default :
                ;
       }

    }

}

