from __future__ import division, print_function

import os
import re
import subprocess

import cv2
import numpy as np

try:
    import rospy
    import tf
    import geometry_msgs
    import gazebo_msgs.srv
except ImportError:
    pass
import time


class suppress_stdout(object):
    '''
    A context manager for doing a "deep suppression" of stdout in
    Python, i.e. will suppress all print, even if the print originates in a
    compiled C/Fortran sub-function.
    '''
    def __init__(self):
        # Open a null file
        while True:
            try:
                self.null_fds =  os.open(os.devnull, os.O_RDWR)
                break
            except OSError:
                time.sleep(1)
        # Save the actual stdout file descriptor
        self.save_fds = os.dup(1)

    def __enter__(self):
        # Assign the null pointers to stdout
        os.dup2(self.null_fds, 1)
        os.close(self.null_fds)

    def __exit__(self, *_):
        # Re-assign the real stdout back
        os.dup2(self.save_fds, 1)
        # Close the null file
        os.close(self.save_fds)


class suppress_stdout_stderr(object):
    '''
    A context manager for doing a "deep suppression" of stdout and stderr in
    Python, i.e. will suppress all print, even if the print originates in a
    compiled C/Fortran sub-function.
       This will not suppress raised exceptions, since exceptions are printed
    to stderr just before a script exits, and after the context manager has
    exited (at least, I think that is why it lets exceptions through).

    '''
    def __init__(self):
        # Open a pair of null files
        self.null_fds =  [os.open(os.devnull,os.O_RDWR) for x in range(2)]
        # Save the actual stdout (1) and stderr (2) file descriptors.
        self.save_fds = (os.dup(1), os.dup(2))

    def __enter__(self):
        # Assign the null pointers to stdout and stderr.
        os.dup2(self.null_fds[0],1)
        os.dup2(self.null_fds[1],2)

    def __exit__(self, *_):
        # Re-assign the real stdout/stderr back to (1) and (2)
        os.dup2(self.save_fds[0],1)
        os.dup2(self.save_fds[1],2)
        # Close the null files
        os.close(self.null_fds[0])
        os.close(self.null_fds[1])


def standarize(data, in_min=0, in_max=255, out_min=-1, out_max=1):
    assert in_min <= data.min() <= data.max() <= in_max
    return (data.astype(float) - in_min) * (out_max - out_min)/(in_max - in_min) + out_min

def destandarize(data, in_min=-1, in_max=1, out_min=0, out_max=255):
    return standarize(data, in_min=in_min, in_max=in_max, out_min=out_min, out_max=out_max)

def linspace2d(start,end,n):
    cols = [np.linspace(s,e,n) for (s,e) in zip(start,end)]
    return np.array(cols).T

def upsample_waypoints(waypoints, max_dist):
    upsampled_waypoints = []
    for wp0, wp1 in zip(waypoints[:-1], waypoints[1:]):
        dist = np.linalg.norm(np.asarray(wp1) - np.asarray(wp0))
        num = np.ceil(dist/max_dist)
        upsampled_waypoints.append(linspace2d(wp0, wp1, num))
    return np.concatenate(upsampled_waypoints)

def transform_from_pose(pose):
    pos = np.asarray([pose.position.x, pose.position.y, pose.position.z])
    quat = np.asarray([pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w])
    return (pos, quat)

def create_pose_from_transform(transform):
    pos, quat = transform
    pose = geometry_msgs.msg.Pose()
    pose.position.x = pos[0]
    pose.position.y = pos[1]
    pose.position.z = pos[2]
    pose.orientation.x = quat[0]
    pose.orientation.y = quat[1]
    pose.orientation.z = quat[2]
    pose.orientation.w = quat[3]
    return pose

def create_pose(xyz, roll, pitch, yaw):
    quat = tf.transformations.quaternion_from_euler(roll, pitch, yaw)
    return create_pose_from_transform((xyz, quat))

def create_pose_msg(xyz, roll, pitch, yaw, frame_id):
    pose_stamped = geometry_msgs.msg.PoseStamped()
    pose_stamped.pose = create_pose(xyz, roll, pitch, yaw)
    pose_stamped.header.frame_id = "/arm_link_0"
    pose_stamped.header.stamp = rospy.Time.now()
    return pose_stamped

def get_model_pose(model_name, relative_entity_name='world'):
    rospy.wait_for_service('gazebo/get_model_state')
    try:
        get_model_state = rospy.ServiceProxy('gazebo/get_model_state', gazebo_msgs.srv.GetModelState)
        res = get_model_state(model_name, relative_entity_name)
        return res.pose
    except rospy.ServiceException as e:
        print("Service call failed: %s"%e)

def set_model_pose(model_name, model_pose, relative_entity_name='world'):
    rospy.wait_for_service('gazebo/set_model_state')
    try:
        set_model_state = rospy.ServiceProxy('gazebo/set_model_state', gazebo_msgs.srv.SetModelState)
        model_state = gazebo_msgs.msg.ModelState()
        model_state.model_name = model_name
        model_state.pose = model_pose
        model_state.reference_frame = relative_entity_name
        set_model_state(model_state)
    except rospy.ServiceException as e:
        print("Service call failed: %s"%e)

def arrowed_line(img, pt1, pt2, color, thickness=1, shift=0, tip_length=0.1):
    # adapted from http://mlikihazar.blogspot.com.au/2013/02/draw-arrow-opencv.html
    if img.ndim == 1:
        img = np.repeat(img[:, :, None], 3, axis=2)
    pt1 = np.asarray(pt1, dtype=int)
    pt2 = np.asarray(pt2, dtype=int)
    color = tuple(color)
    # draw arrow tail
    cv2.line(img, tuple(pt1), tuple(pt2), color, thickness=thickness, shift=shift)
    # calc angle of the arrow
    angle = np.arctan2(pt1[1]-pt2[1], pt1[0]-pt2[0])
    # starting point of first line of arrow head
    pt = (int(pt2[0] + tip_length * np.cos(angle + np.pi/4)),
          int(pt2[1] + tip_length * np.sin(angle + np.pi/4)))
    # draw first half of arrow head
    cv2.line(img, tuple(pt), tuple(pt2), color, thickness=thickness, shift=shift)
    # starting point of second line of arrow head
    pt = (int(pt2[0] + tip_length * np.cos(angle - np.pi/4)),
          int(pt2[1] + tip_length * np.sin(angle - np.pi/4)))
    # draw second half of arrow head
    cv2.line(img, tuple(pt), tuple(pt2), color, thickness=thickness, shift=shift)

def resize_from_scale(image, rescale_factor):
    return cv2.resize(image, (0, 0), fx=rescale_factor, fy=rescale_factor, interpolation=cv2.INTER_NEAREST)

def resize_from_height(image, height, ret_factor=False):
    h, w = image.shape[:2]
    rescale_factor = height / float(h)
    image = resize_from_scale(image, rescale_factor)
    if ret_factor:
        return (image, rescale_factor)
    return image

def create_vis_image(image_curr_data, vel_data, image_diff_data, rescale_factor=1, draw_vel=True, rescale_vel=10):
    assert np.all(image_curr_data >= 0)
    assert np.all(-1 <= image_diff_data) and np.all(image_diff_data <= 1)
    image_curr = image_curr_data.transpose(1, 2, 0)
    if image_curr.shape[2] == 1:
        image_curr = np.squeeze(image_curr, axis=2)
    image_diff = image_diff_data.transpose(1, 2, 0)
    if image_diff.shape[2] == 1:
        image_diff = np.squeeze(image_diff, axis=2)
    image_next = np.clip(image_curr + image_diff, 0, 1)

    image_curr = (image_curr * 255.0).astype(np.uint8)
    image_diff = ((image_diff + 1.0) * 255.0 / 2).astype(np.uint8)
    image_next = (image_next * 255.0).astype(np.uint8)

    images = [resize_from_scale(image, rescale_factor) for image in [image_curr, image_diff, image_next]]

    if draw_vel:
        # change from grayscale to bgr format
        images = [np.repeat(image[:, :, None], 3, axis=2) if image.ndim == 2 else image for image in images]
        h, w = images[0].shape[:2]
        # draw coordinate system
        arrowed_line(images[0],
                     (w/2, h/2),
                     (w/2 + rescale_factor, h - h/2),
                     [0, 0, 255],
                     thickness=2,
                     tip_length=rescale_factor*0.2)
        arrowed_line(images[0],
                     (w/2, h/2),
                     (w/2, h - (h/2 + rescale_factor)),
                     [0, 255, 0],
                     thickness=2,
                     tip_length=rescale_factor*0.2)
        # draw rescaled velocity
        arrowed_line(images[0],
                     (w/2, h/2),
                     (w/2 + vel_data[0] * rescale_vel * rescale_factor,
                      h - (h/2 + vel_data[1] * rescale_vel * rescale_factor)),
                     [255, 0, 0],
                     thickness=2,
                     tip_length=rescale_factor*0.4)

    vis_image = np.concatenate(images, axis=1)
    return vis_image

def serial_number_from_device_id(device_id):
    output = subprocess.check_output("udevadm info -a -n /dev/video%d | grep '{serial}' | head -n1"%device_id, shell=True)
    match = re.match('\s*ATTRS{serial}=="([A-Z0-9]+)"\n', output)
    if not match:
        raise RuntimeError('Device id %d does not exist'%device_id)
    serial_number = match.group(1)
    return serial_number

def device_id_from_serial_number(serial_number):
    for dev_file in  os.listdir('/dev'):
        match = re.match('video(\d)$', dev_file)
        if match:
            device_id = int(match.group(1))
            if serial_number == serial_number_from_device_id(device_id):
                return device_id
    return None

def serial_number_from_camera_id(camera_id):
    serial_number = dict([('A', 'EE96593F'),
                          ('B', 'E8FE493F'),
                          ('C', 'C3D6593F'),
                          ('D', '6ACE493F')])
    if camera_id not in serial_number:
        raise RuntimeError('Camera id %s does not exist'%camera_id)
    return serial_number[camera_id]

def camera_id_from_serial_number(serial_number):
    camera_id = dict([('EE96593F', 'A'),
                      ('E8FE493F', 'B'),
                      ('C3D6593F', 'C'),
                      ('6ACE493F', 'D')])
    if serial_number not in camera_id:
        raise RuntimeError('Serial number %s does not exist'%serial_number)
    return camera_id[serial_number]

def device_id_from_camera_id(camera_id):
    return device_id_from_serial_number(serial_number_from_camera_id(camera_id))

def yes_or_no(question):
    assert isinstance(question, str) or isinstance(question, str)
    while True:
        yn = input(question + " ([y]/n): ")
        if yn == 'y' or yn == '':
            return True
        elif yn == 'n':
            return False

def obs_from_image(image):
    """
    image: height x width x channel array of type uint8 with values in [0, 255]
    """
    obs = (image.astype(float) / 255.0) * 2.0 - 1.0
    if obs.ndim == 2:
        obs = obs[None, :, :]
    else:
        obs = obs.transpose(2, 0, 1)
    return obs

def image_from_obs(obs):
    """
    obs: channel x height x width array of type float with values in [-1, 1]
    """
    image = obs.transpose(1, 2, 0)
    image = ((image + 1.0) * 255.0 / 2.0).astype(np.uint8)
    return image
