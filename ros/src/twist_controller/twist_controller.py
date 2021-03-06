import math
import rospy
from yaw_controller import YawController
from pid import PID
from lowpass import LowPassFilter

GAS_DENSITY = 2.858
ONE_MPH = 0.44704


class Controller(object):
    def __init__(self, vehicle_mass, fuel_capacity, brake_deadband, decel_limit, accel_limit, wheel_radius, wheel_base, steer_ratio, max_lat_accel, max_steer_angle, max_throttle_percent):
        self.yaw_controller = YawController(wheel_base, steer_ratio, 0.1, max_lat_accel, max_steer_angle)

        #Steering PID controller
        kp = 1.2
        ki = 0.0
        kd = 1.4
        mn = -max_steer_angle #minial steer angle
        mx = max_steer_angle #maximum steer angle
        self.steering_controller = PID(kp, ki, kd, mn, mx)

        tau = 0.05  #1 / (2pi*tau) = cutoff frequency
        ts = 0.02 # sample time
        self.vel_lpf = LowPassFilter(tau, ts)

        self.vehicle_mass = vehicle_mass
        self.fuel_capacity = fuel_capacity
        self.brake_deadband = brake_deadband
        self.decel_limit = decel_limit
        self.accel_limit = accel_limit
        self.wheel_radius = wheel_radius

        self.last_time = rospy.get_time()
        self.max_vel = 0.001
        self.last_throttle = 0.
        self.last_brake = 100.
        self.last_steering = 0.
        #self.PID_steering = 0.

    def control(self, linear_vel, angular_vel, current_vel, dbw_enabled, max_throttle_percent, current_cte, current_angular_vel):
        # return throttle, brake, steer

        if not dbw_enabled:
            self.steering_controller.reset()
            return 0., 0., 0.
        
        #rospy.loginfo('self.max_vel: %f', self.max_vel)
        target_vel = linear_vel
        if target_vel > self.max_vel:
            self.max_vel = target_vel
        
        filt_current_vel = self.vel_lpf.filt(current_vel)
        #rospy.loginfo('angular_vel: %f', angular_vel)
        #steering = self.yaw_controller.get_steering(twist.twist.linear.x, twist.twist.angular.z, velocity.twist.linear.x)
        #steering = steering + current_cte
        #rospy.loginfo('yaw_steering : %.3f', yaw_steering)
        
        current_time = rospy.get_time()
        sample_time = current_time - self.last_time
        self.last_time = current_time
        #rospy.loginfo('Sample time: %.3f', sample_time)
      	angular_vel_delta = angular_vel - current_angular_vel
        #rospy.loginfo('Desired angular velocity: %.3f', angular_vel)
        #rospy.loginfo('Angular velocity delta: %.3f', angular_vel_delta)
        PID_angular_vel = self.steering_controller.step(angular_vel_delta, sample_time)
	total_angular_vel = PID_angular_vel + angular_vel
	#rospy.loginfo('PID angular velocity: %.3f', total_angular_vel)
        #steering = yaw_steering + PID_steering
        #rospy.loginfo('PID steering : %.3f', PID_steering)
        steering = self.yaw_controller.get_steering(linear_vel, total_angular_vel, filt_current_vel)
        #rospy.loginfo('CTE : %.3f', current_cte)
        #rospy.loginfo('PID steering: %f', steering)
        
        #smoothing steering control

        if (steering - self.last_steering) > 0.2:
            steering = self.last_steering + 0.2
        elif (steering - self.last_steering) < -0.2:
            steering = self.last_steering - 0.2
        
        self.last_steering = steering

        #rospy.loginfo('steering: %f', steering)

        vel_error = linear_vel - filt_current_vel
        
        #acceleration = self.throttle_controller.step(vel_error, sample_time)
        
        # smooth acceleration algorithm based on "An Intelligent Vehicle Based on an Improved PID Speed Control Algorithm for Driving Trend Graphs" paper
        # by Zhenhua Pan, Hong Bao, Feng Pan, Cheng Xu
        # link: http://ijssst.info/Vol-17/No-30/paper19.pdf
        smooth_acc = ((linear_vel * linear_vel) - (filt_current_vel * filt_current_vel))
          
        #rospy.loginfo('smooth acceleration: %f', smooth_acc)
        #rospy.loginfo('linear_vel: %f', linear_vel)
        #rospy.loginfo('angular_vel: %.3f   linear_vel: %.3f   filt_current_vel: %.3f   vel_error: %.3f  acceleration: %.3f', angular_vel, linear_vel, filt_current_vel, vel_error, acceleration)
        
        if smooth_acc >= 0:
            # converting smooth_acc values to throttle acceptable values
            throttle = smooth_acc * (max_throttle_percent - (linear_vel * 0.018)) / (self.max_vel * self.max_vel) + (linear_vel * 0.018)
        else:
            throttle = 0
        
        if throttle > max_throttle_percent:
            throttle = max_throttle_percent
        
        #smoothing throttle acceleration and deceleration    
        if (throttle > 0.005) and (throttle - self.last_throttle) > 0.005:
            throttle = max((self.last_throttle + 0.0025), 0.005)
        if throttle > 0.005 and (throttle - self.last_throttle) < -0.05:
            throttle = self.last_throttle - 0.05
        
        self.last_throttle = throttle
        
        brake = 0.

        if linear_vel == 0. and filt_current_vel < 0.1:
            throttle = 0.
            brake = 700. # N*m - to hold the car in place if we are stopped at a light. Acceleration - 1m/s^2
        elif throttle < 0.005 and vel_error < 0.:
            throttle = 0.
            #decel = max(vel_error, self.decel_limit)
            decel = max((smooth_acc * 5), self.decel_limit)
            brake = abs(decel) * self.vehicle_mass * self.wheel_radius # Torque N*m
            #smoothing brake
            if brake > 100 and (brake - self.last_brake) > 20:
                brake = max((self.last_brake + 20), 100)
        
        if brake > 20 and (brake - self.last_brake) > 20:
            brake = max((self.last_brake + 20), 20)
        
        #rospy.loginfo('brake: %f', brake)
        #rospy.loginfo('trottle: %f', throttle)
        self.last_brake = brake
        
        return throttle, brake, steering
