from turtle import Turtle
MOVE_DISTANCE = 20
UP = 90
DOWN = 270
LEFT = 180
RIGHT = 0
class Snake:

    def __init__(self, x_cor):
        self.segments = []
        self.create_snake(x_cor)
        self.head = self.segments[0]

    def create_snake(self,x_cor):
        for index in range(3):
            new_segment =  Turtle("square")
            new_segment.color("white")
            new_segment.penup()
            new_segment.setposition(x_cor,0)
            self.segments.append(new_segment)
            x_cor -= 20

    def movement(self):
        for seg_num in range(len(self.segments)-1, 0, -1):
            new_x = self.segments[seg_num-1].xcor()
            new_y = self.segments[seg_num-1].ycor()
            self.segments[seg_num].goto(new_x,new_y)
        self.head.forward(MOVE_DISTANCE)

    def up(self):
        if self.head.heading() != DOWN:
            self.head.setheading(UP)

    def down(self):
        if self.head.heading() != UP:
            self.head.setheading(DOWN)

    def left(self):
        if self.head.heading() != RIGHT:
            self.head.setheading(LEFT)

    def right(self):
        if self.head.heading() != LEFT:
            self.head.setheading(RIGHT)