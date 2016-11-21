#!/usr/bin/env python3

from launchpad import *

wheel = ColorWheel(radius=4, length=20)
loop = Loop(wheel, 500)

if __name__ == '__main__':
    lp = Launchpad()
    lp.play(loop, 2000)
