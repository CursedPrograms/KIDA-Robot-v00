import pygame
from gpiozero import Motor

class MotorController:
    def __init__(self, left_pins=(24, 23), right_pins=(5, 6)):
        self.left = Motor(forward=left_pins[0], backward=left_pins[1])
        self.right = Motor(forward=right_pins[0], backward=right_pins[1])

    def stop(self):
        self.left.stop()
        self.right.stop()

    def forward(self, speed=1.0):
        self.left.forward(speed)
        self.right.forward(speed)

    def backward(self, speed=1.0):
        self.left.backward(speed)
        self.right.backward(speed)

    def turn_left(self, speed=1.0):
        self.left.backward(speed)
        self.right.forward(speed)

    def turn_right(self, speed=1.0):
        self.left.forward(speed)
        self.right.backward(speed)

    def control_mode_2(self, keys, speed):
        left_active = right_active = False
        if keys[pygame.K_q]:
            self.left.forward(speed)
            left_active = True
        elif keys[pygame.K_a]:
            self.left.backward(speed)
            left_active = True
        else:
            self.left.stop()

        if keys[pygame.K_w]:
            self.right.forward(speed)
            right_active = True
        elif keys[pygame.K_s]:
            self.right.backward(speed)
            right_active = True
        else:
            self.right.stop()

        return left_active, right_active
