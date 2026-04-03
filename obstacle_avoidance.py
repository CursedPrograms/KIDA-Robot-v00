from gpiozero import DistanceSensor
import time

class ObstacleAvoidance:
    def __init__(self, trigger_pin=27, echo_pin=22, motors=None, threshold=0.5):
        # Faster response (no smoothing delay)
        self.sensor = DistanceSensor(
            echo=echo_pin,
            trigger=trigger_pin,
            max_distance=2.0,
            queue_len=1
        )
        self.motors = motors
        self.threshold = threshold
        self.turn_left_next = True
        
        # More realistic speeds for a Pi 3 robot
        self.min_speed = 0.3
        self.max_speed = 0.6
        
        # Stuck detection
        self.obstacle_count = 0
        self.last_obstacle_time = 0
        self.stuck_threshold = 3  # Number of obstacles in quick succession
        self.stuck_time_window = 2.0  # Within 2 seconds
        self.committed_direction = None  # Will be 'left' or 'right'
        self.commitment_timeout = 5.0  # Stay committed for 5 seconds
        self.commitment_start_time = 0
    
    def get_distance(self):
        try:
            return self.sensor.distance
        except Exception:
            return None
    
    def _map_speed(self, distance):
        if distance >= self.threshold:
            return self.max_speed
        if distance <= 0:
            return self.min_speed
        ratio = distance / self.threshold
        speed = self.min_speed + (self.max_speed - self.min_speed) * ratio
        return max(self.min_speed, min(self.max_speed, speed))
    
    def _detect_stuck(self):
        """Check if robot is repeatedly hitting obstacles (stuck pattern)"""
        current_time = time.time()
        
        # Check if we're still in the time window
        if current_time - self.last_obstacle_time < self.stuck_time_window:
            self.obstacle_count += 1
        else:
            # Reset counter if too much time has passed
            self.obstacle_count = 1
        
        self.last_obstacle_time = current_time
        
        # If we hit stuck threshold, commit to a direction
        if self.obstacle_count >= self.stuck_threshold:
            if self.committed_direction is None:
                # Choose direction based on current preference
                self.committed_direction = 'left' if self.turn_left_next else 'right'
                self.commitment_start_time = current_time
                print(f"🔄 STUCK DETECTED! Committing to turn {self.committed_direction.upper()}")
            return True
        return False
    
    def _should_stay_committed(self):
        """Check if we should still follow committed direction"""
        if self.committed_direction is None:
            return False
        
        # Release commitment after timeout
        if time.time() - self.commitment_start_time > self.commitment_timeout:
            print(f"✅ Commitment timeout - resuming normal operation")
            self.committed_direction = None
            self.obstacle_count = 0
            return False
        
        return True
    
    def check_and_avoid(self):
        if self.motors is None:
            return False
        
        distance = self.get_distance()
        if distance is None:
            return False
        
        # 🚨 OBSTACLE DETECTED
        if distance < self.threshold:
            # Check if we're stuck
            is_stuck = self._detect_stuck()
            
            self.motors.stop()
            time.sleep(0.05)
            
            # Reverse briefly
            self.motors.backward(self.min_speed)
            start_time = time.time()
            while time.time() - start_time < 0.3:
                pass
            self.motors.stop()
            time.sleep(0.05)
            
            # Decide turn direction
            if self._should_stay_committed():
                # Stuck mode: always turn the same way
                turn_direction = self.committed_direction
                # Longer turn when stuck
                turn_duration = 0.7
            else:
                # Normal mode: alternate
                turn_direction = 'left' if self.turn_left_next else 'right'
                turn_duration = 0.55
                self.turn_left_next = not self.turn_left_next
            
            # Execute turn
            if turn_direction == 'left':
                self.motors.turn_left(self.min_speed)
            else:
                self.motors.turn_right(self.min_speed)
            
            start_time = time.time()
            while time.time() - start_time < turn_duration:
                pass
            
            self.motors.stop()
            return True
        
        # ✅ PATH CLEAR
        else:
            # Reset stuck detection if we have clear path
            if distance > self.threshold * 1.5:  # Good clearance
                if self.obstacle_count > 0:
                    self.obstacle_count = max(0, self.obstacle_count - 1)
            
            speed = self._map_speed(distance)
            self.motors.forward(speed)
            return False
    
    def cleanup(self):
        if self.motors:
            self.motors.stop()
        self.sensor.close()