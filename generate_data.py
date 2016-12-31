import argparse
import yaml
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.animation as manimation
from gui.grid_image_visualizer import GridImageVisualizer
import envs
import utils


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('env_fname', type=str, help='config file with environment arguments')
    parser.add_argument('pol_fname', type=str, help='config file with policy arguments')
    parser.add_argument('--output_dir', '-o', type=str, default=None)
    parser.add_argument('--num_trajs', '-n', type=int, default=10, metavar='N', help='total number of data points is N*T')
    parser.add_argument('--num_steps', '-t', type=int, default=10, metavar='T', help='number of time steps per trajectory')
    parser.add_argument('--visualize', '-v', type=int, default=None)
    parser.add_argument('--record_file', '-r', type=str, default=None)
    args = parser.parse_args()

    with open(args.env_fname) as yaml_string:
        env_config = yaml.load(yaml_string)
        if issubclass(env_config['class'], envs.RosEnv):
            import rospy
            rospy.init_node("generate_data")
        env = utils.from_config(env_config)

    with open(args.pol_fname) as yaml_string:
        policy_config = yaml.load(yaml_string)
        replace_config = {'env': env,
                          'action_space': env.action_space}
        try:
            replace_config['target_env'] = env.car_env
        except AttributeError:
            pass
        pol = utils.from_config(policy_config, replace_config=replace_config)

    if args.output_dir:
        container = utils.container.ImageDataContainer(args.output_dir, 'x')
        container.reserve(env.sensor_names + ['state'], (args.num_trajs, args.num_steps + 1))
        container.reserve(['action', 'state_diff'], (args.num_trajs, args.num_steps))
        container.add_info(environment_config=env.get_config())
        container.add_info(env_spec_config=envs.EnvSpec(env).get_config())
        container.add_info(policy_config=pol.get_config())
    else:
        container = None

    if args.record_file and not args.visualize:
        args.visualize = 1
    if args.visualize:
        fig = plt.figure(figsize=(16, 12), frameon=False, tight_layout=True)
        gs = gridspec.GridSpec(1, 1)
        image_visualizer = GridImageVisualizer(fig, gs[0], len(env.sensor_names))
        plt.show(block=False)

        if args.record_file:
            FFMpegWriter = manimation.writers['ffmpeg']
            writer = FFMpegWriter(fps=1.0 / env.dt)
            writer.setup(fig, args.record_file, fig.dpi)

    import time
    start_time = time.time()
    done = False
    for traj_iter in range(args.num_trajs):
        print('traj_iter', traj_iter)
        try:
            state = pol.reset()
            obs = env.reset(state)
            for step_iter in range(args.num_steps):
                if container:
                    container.add_datum(traj_iter, step_iter, state=state, **dict(zip(env.sensor_names, obs)))

                action = pol.act(obs)
                obs, _, _, _ = env.step(action)  # action is updated in-place if needed

                if container:
                    prev_state, state = state, env.get_state()
                    container.add_datum(traj_iter, step_iter, action=action, state_diff=state - prev_state)
                    if step_iter == (args.num_steps - 1):
                        container.add_datum(traj_iter, step_iter + 1, state=state, **dict(zip(env.sensor_names, obs)))

                if args.visualize:
                    env.render()
                    try:
                        image_visualizer.update(obs)
                        if args.record_file:
                            writer.grab_frame()
                    except:
                        done = True
                    if done:
                        break
            if done:
                break
        except KeyboardInterrupt:
            break
    env.close()
    if args.record_file:
        writer.finish()
    if container:
        container.close()
    end_time = time.time()
    print("average FPS: {}".format(args.num_trajs * (args.num_steps + 1) / (end_time - start_time)))


if __name__ == "__main__":
    main()
