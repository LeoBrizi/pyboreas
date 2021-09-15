import numpy as np
from scipy.spatial.transform import Rotation as R

from data_classes.bounding_boxes import BoundingBox2D

def to_T(C, r):
    T = np.concatenate((C, r), axis=1)
    T = np.concatenate((T, [[0, 0, 0, 1]]), axis=0)
    return T

def velodyne_frame_from_imu(raw_heading, r_io, T_iv=None):
    """
    Computes matrices needed to move from GPS (odometry) frame
    to sensor (Velodyne) frame from transformation between IMU and odom frames.

    :param raw_heading: IMU heading as quaternion
    :param r_io: Vector from origin of odom frame to origin of IMU frame expressed in odom frame
    :param T_iv: Transformation matrix from velodyne frame to IMU frame
    :return T_vo: Transformation matrix from odom to Velodyne
            C_vo_yaw: Yaw rotation matrix from odom to Velodyne
    """
    # Transformation matrix from Odom to IMU
    raw_heading = -np.roll(raw_heading, -1)
    raw_heading[0] = -raw_heading[0]
    raw_heading[1] = -raw_heading[1]
    raw_heading[2] = -raw_heading[2]
    C_io = R.from_quat(raw_heading).as_matrix()
    r_oi = -np.matmul(C_io, r_io)
    T_io = np.concatenate((C_io, r_oi), axis=1)
    T_io = np.concatenate((T_io, [[0, 0, 0, 1]]), axis=0)

    # Transform matrix from IMU to Velodyne
    if T_iv is None:
        C_iv = np.array([[0, -1, 0],
                        [1, 0, 0],
                        [0, 0, 1]])
        C_vi = C_iv.T
        r_vi = np.array([[0, 0, 0.45]]).T
        r_iv = -np.matmul(C_vi, r_vi)
        T_vi = to_T(C_vi, r_iv)
    else:
        T_vi = np.linalg.inv(T_iv)
        C_vi = T_vi[0:3,0:3]

    # Transformation matrix from Odom to Velodyne
    T_vo = np.matmul(T_vi, T_io)

    # Rotation matrix for bounding boxes (yaw only)
    raw_heading_yaw = raw_heading
    raw_heading_yaw[0] = 0  # Pitch to 0
    raw_heading_yaw[1] = 0  # Roll to 0
    C_io_yaw = R.from_quat(raw_heading_yaw).as_matrix()
    C_vo_yaw = np.matmul(C_vi, C_io_yaw)

    return T_vo, C_vo_yaw

def get_camera_timestamp(raw_data, offset=0):
    """
    Get lidar and camera timestamp from the loaded json. Applies an offset to account for the camera-lidar timestamp differences.
    :param raw_data: data from point cloud json file
    """
    lidar_time_stamp = raw_data['timestamp']
    camera_timestamp = lidar_time_stamp + offset
    return lidar_time_stamp, camera_timestamp

def get_dataset_offset_camera_ts(dataset):
    if dataset == "scale":
        return 6.3e9
    elif dataset == "boreas":
        return 0
    else:
        raise Exception('Unknown dataset!')

def get_offset_camera_ts(timestamp):
    return int(-1.634e-07 * timestamp + 2.675e+11 + timestamp)

def get_device_pose(raw_data, T_iv=None):
    """
    Get pose of IMU from recorded json data file
    :param raw_data: data from point cloud json file
    :param T_iv: transformation between IMU and Lidar
    """
    raw_heading = np.array(list(raw_data['device_heading'].values()))
    r_io = np.array([list(raw_data['device_position'].values())]).T
    return velodyne_frame_from_imu(raw_heading, r_io, T_iv)

def transform_points(T, raw_pcd, keep_prob=1.0):
    """
    Transform raw lidar points by a SE3 transformation
    :param T_vo: required transformation
    :param raw_pcd: original point cloud data
    """
    points = np.zeros([len(raw_pcd), 3])
    for i in range(len(raw_pcd)):
        points[i][0] = raw_pcd[i]['x']
        points[i][1] = raw_pcd[i]['y']
        points[i][2] = raw_pcd[i]['z']
    points = points[np.random.choice(len(raw_pcd), int(keep_prob*len(raw_pcd)), replace=False)]
    points = np.matmul(T,
                       np.vstack((points.T, np.ones(points.shape[0]))))
    points = points.T[:]
    return points

def transform_bounding_boxes(T, C_yaw, raw_labels):
    """
    Generate bounding boxes from labels and transform them
    by a SE3 transformation
    :param T: required SE3 transformation
    :param C_yaw: yaw component of the SE3 transformation
    :param raw_labels: original label data
    """
    boxes = []
    for i in range(len(raw_labels)):
        # Load Labels
        bbox_raw_pos = np.concatenate(
            (np.fromiter(raw_labels[i]['position'].values(), dtype=float), [1]))
        # Create Bounding Box
        pos = np.matmul(T, np.array([bbox_raw_pos]).T)[:3]
        rotation = np.matmul(C_yaw, rot_z(raw_labels[i]['yaw']))
        rot_to_yaw_pitch_roll(rotation)
        extent = np.array(list(raw_labels[i]['dimensions'].values())).reshape(3, 1)  # Convert to 2d
        box = BoundingBox2D(pos, rotation, extent, raw_labels[i]['label'])
        boxes.append(box)
    return boxes

def transform_data_to_sensor_frame(raw_data, raw_labels=None, pcd_down_sample_prob=1.0, T_iv=None):
    """
    Transforms point cloud and label data from GPS (odom) frame
    to sensor (Velodyne) frame
    :param raw_data: data from point cloud json file
    :param raw_labels: data from label csv file
    :param T_iv: transformation between IMU and Lidar
    :return: point cloud numpy array and bounding boxes tuple in sensor frame
    """
    raw_pcd = raw_data['points']
    
    # Get transformation matrices
    T_vo, C_vo_yaw = get_device_pose(raw_data, T_iv)

    # Transform Points
    points = transform_points(T_vo, raw_pcd, pcd_down_sample_prob)

    # Transform Labels into Bounding Boxes
    if raw_labels != None:
        boxes = transform_bounding_boxes(T_vo, C_vo_yaw, raw_labels)
    else:
        boxes = []

    return points, boxes


def rot_x(alpha):
    return np.array([[1, 0, 0],
                     [0, np.cos(alpha), -np.sin(alpha)],
                     [0, np.sin(alpha), np.cos(alpha)]])


def rot_y(beta):
    return np.array([[np.cos(beta), 0, np.sin(beta)],
                     [0, 1, 0],
                     [-np.sin(beta), 0, np.cos(beta)]])


def rot_z(gamma):
    return np.array([[np.cos(gamma), -np.sin(gamma), 0],
                     [np.sin(gamma), np.cos(gamma), 0],
                     [0, 0, 1]])


def rot_to_yaw_pitch_roll(C, eps=1e-15):
    i = 2
    j = 1
    k = 0
    c_y = np.sqrt(C[i, i] ** 2 + C[j, i] ** 2)
    if c_y > eps:
        roll = np.arctan2(C[j, i], C[i, i])
        pitch = np.arctan2(-C[k, i], c_y)
        yaw = np.arctan2(C[k, j], C[k, k])
    else:
        roll = 0
        pitch = np.arctan2(-C[k, i], c_y)
        yaw = np.arctan2(-C[j, k], C[j, j])
    return yaw, pitch, roll
