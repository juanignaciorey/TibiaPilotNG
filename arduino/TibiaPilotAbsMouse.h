/*
  Vendored from absmouse (Jonathan Edgecombe, 2017).
  https://github.com/jonathanedgecombe/absmouse
  Single change: #include <HID.h> so the core USB HID is used (defines _USING_HID)
  before any other library can shadow "HID.h".
*/
#ifndef TIBIAPILOT_ABS_MOUSE_h
#define TIBIAPILOT_ABS_MOUSE_h

#include <HID.h>

#if defined(_USING_HID)
#define TIBIAPILOT_ABS_MOUSE_SUPPORTED 1
#else
#define TIBIAPILOT_ABS_MOUSE_SUPPORTED 0
#endif

#define MOUSE_LEFT 0x01
#define MOUSE_RIGHT 0x02
#define MOUSE_MIDDLE 0x04

class AbsMouse_
{
private:
 uint8_t _buttons;
 uint16_t _x;
 uint16_t _y;
 uint32_t _width;
 uint32_t _height;
 bool _autoReport;

public:
 AbsMouse_(void);
 void init(uint16_t width = 32767, uint16_t height = 32767, bool autoReport = true);
 void report(void);
 void move(uint16_t x, uint16_t y);
 void press(uint8_t b = MOUSE_LEFT);
 void release(uint8_t b = MOUSE_LEFT);
};
extern AbsMouse_ AbsMouse;

#endif
