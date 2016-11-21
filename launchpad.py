import mido
import time
from collections import namedtuple
import random
import copy
import colorsys
import math

RGB = namedtuple('RGB', ['r', 'g', 'b'])

class Effect:
    def length(self):
        return 1

    def notes(self, tick):
        return []

class Note(Effect):
    def __init__(self, pos, color):
        self.pos = pos
        self.color = color

    def length(self):
        return 1

    def notes(self, tick):
        return [self]

class Rectangle(Effect):
    def __init__(self, ll, ur, color):
        self._notes = [Note((x, y), color) \
                      for x in range(ll[0], ur[0] + 1) \
                      for y in range(ll[1], ur[1] + 1)]

    def length(self):
        return 1

    def notes(self, tick):
        return self._notes

Fullscreen = lambda color: Rectangle((-1, -1), (8, 8), color)
Clear = lambda: Fullscreen(0)

class Translate(Effect):
    def __init__(self, effect, offset):
        self.child = effect
        self.offset = offset

    def length(self):
        return self.child.length()

    def notes(self, tick):
        return [Note((n.pos[0] + self.offset[0], n.pos[1] + self.offset[1]), n.color) \
                     for n in self.child.notes(tick)]

class Sequential(Effect):
    def __init__(self, *effects):
        self.effects = effects

    def length(self):
        sum = 0
        for eff in self.effects:
            sum += eff.length()
        return sum

    def notes(self, tick):
        for eff in self.effects:
            if tick >= eff.length():
                tick -= eff.length()
            else:
                return eff.notes(tick)

class Concurrent(Effect):
    def __init__(self, *effects):
        self.effects = pad_effects(effects)

    def length(self):
        if len(self.effects) == 0:
            return 0
        return self.effects[0].length()

    def notes(self, tick):
        lst = []
        for eff in self.effects:
            lst.extend(eff.notes(tick))
        return lst

class Loop(Effect):
    def __init__(self, effect, n):
        self.child = effect
        self.n = n

    def length(self):
        return self.child.length() * self.n

    def notes(self, tick):
        return self.child.notes(tick % self.child.length())

class PaddedEffect(Effect):
    def __init__(self, effect, length, notes):
        self.effect = effect
        self._length = length
        self._notes = notes

    def length(self):
        return self._length

    def notes(self, tick):
        if tick < self.effect.length():
            return self.effect.notes(tick)
        else:
            return self._notes

def pad_effects(effects, pad_func=lambda x: []):
    if len(effects) == 0:
        return []

    length = max(effects, key=lambda x: x.length()).length()
    return [PaddedEffect(e, length, pad_func(e)) if e.length() < length else e \
            for e in effects]

class Random(Effect):
    def __init__(self, *effects):
        self.effects = pad_effects(effects)

        self.current_effect = None

    def length(self):
        if len(self.effects) == 0:
            return 0
        return self.effects[0].length()

    def notes(self, tick):
        if len(self.effects) == 0:
            return []

        if tick == 0:
            if self.current_effect is None:
                self.current_effect = random.randint(0, len(self.effects) - 1)
            else:
                current_effect = random.randint(0, len(self.effects) - 2)
                if current_effect >= self.current_effect:
                    current_effect += 1
                self.current_effect = current_effect

        if tick >= self.effects[self.current_effect].length():
            return []
        return self.effects[self.current_effect].notes(tick)

class RandomColor(Effect):
    def __init__(self, effect, low=0, high=127):
        self.child = effect
        self.low = low
        self.high = high

    def length(self):
        return self.child.length()

    def notes(self, tick):
        lst = []
        for note in self.child.notes(tick):
            new_note = copy.deepcopy(note)
            new_note.color = random.randint(self.low, self.high)
            lst.append(new_note)
        return lst

class ColorWheel(Effect):
    def __init__(self, center=(3.5, 3.5), radius=3, start_theta=0, delta_theta=2 * math.pi, length=1):
        self.center = center
        self.max_radius = radius
        self.start_theta = start_theta
        self.delta_theta = delta_theta
        self._length = length

    def length(self):
        return self._length

    def notes(self, tick):
        theta_offset = (tick / self.length() * self.delta_theta)

        notes_lst = []
        for x in range(-1, 9):
            for y in range(-1, 9):
                new_x, new_y = (x - self.center[0]) / self.max_radius, (y - self.center[1]) / self.max_radius
                h = ((math.atan2(new_y, new_x) - self.start_theta - theta_offset) % (2 * math.pi)) / (2 * math.pi)
                s = ((new_x ** 2) + (new_y ** 2)) ** 0.5
                s **= 1/2
                v = 0.2

                rgb = colorsys.hsv_to_rgb(h, s, v)
                notes_lst.append(Note((x, y), RGB(rgb[0], rgb[1], rgb[2])))

        return notes_lst

class Launchpad:
    MAX_BRIGHTNESS = 63

    def __init__(self):
        self.port = mido.open_ioport('Launchpad Pro MIDI 1')

        buf_size = 10 * 10
        self.buf = [0 for i in range(buf_size)]
        self.back_buf = [0 for i in range(buf_size)]

    def play(self, effect, bpm):
        def reset_buf():
            self.buf, self.back_buf = self.back_buf, self.buf
            for i in range(len(self.buf)):
                self.buf[i] = 0

        def draw_effect(effect, tick):
            for note in effect.notes(tick):
                x, y = note.pos
                midi_note = y * 10 + x + 11
                if midi_note >= 0 and midi_note < len(self.buf):
                    self.buf[midi_note] = note.color

        def rgb_message(midi_note, rgb):
            prefix = [0, 32, 41, 2, 16, 11]

            def brightness_of_compon(c):
                scaled = int(self.MAX_BRIGHTNESS * c)

                if scaled < 0:
                    return 0
                if scaled > self.MAX_BRIGHTNESS:
                    return self.MAX_BRIGHTNESS
                return scaled

            data = [
                midi_note,
                brightness_of_compon(rgb.r),
                brightness_of_compon(rgb.g),
                brightness_of_compon(rgb.b),
            ]

            return mido.Message(type='sysex', data=prefix + data)

        def write_buf():
            for midi_note, (color, back_color) in enumerate(zip(self.buf, self.back_buf)):
                if color != back_color:
                    msg = None
                    if isinstance(color, RGB):
                        msg = rgb_message(midi_note, color)
                    else:
                        msg = mido.Message(type='note_on', note=midi_note, velocity=color)

                    self.port.send(msg)

        period = 60 / bpm
        for i in range(effect.length()):
            start_time = time.time()

            reset_buf()
            draw_effect(effect, i)
            write_buf()

            sleep_time = period - (time.time() - start_time)
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                print('Unable to maintain {} bpm!'.format(bpm))

        reset_buf()
        write_buf()
