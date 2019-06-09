# Reference: http://inoryy.com/post/tensorflow2-deep-reinforcement-learning/

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from tensorboardX import SummaryWriter
from cleanrl.common import preprocess_obs_space, preprocess_ac_space
import gym_microrts
import argparse
import numpy as np
import gym
import time
import random

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='A2C agent')
    # Common arguments
    parser.add_argument('--exp-name', type=str, default="dummy",
                       help='the name of this experiment')
    parser.add_argument('--gym-id', type=str, default="Microrts-v0",
                       help='the id of the gym environment')
    parser.add_argument('--learning-rate', type=float, default=7e-4,
                       help='the learning rate of the optimizer')
    parser.add_argument('--seed', type=int, default=5,
                       help='seed of the experiment')
    parser.add_argument('--episode-length', type=int, default=2000,
                       help='the maximum length of each episode')
    parser.add_argument('--total-timesteps', type=int, default=5000,
                       help='total timesteps of the experiments')
    parser.add_argument('--prod-mode', type=bool, default=False,
                       help='run the script in production mode and use wandb to log outputs')
    
    # Algorithm specific arguments
    parser.add_argument('--gamma', type=float, default=0.99,
                       help='the discount factor gamma')
    parser.add_argument('--vf-coef', type=float, default=0.25,
                       help="value function's coefficient the loss function")
    parser.add_argument('--max-grad-norm', type=float, default=0.5,
                       help='the maximum norm for the gradient clipping')
    parser.add_argument('--ent-coef', type=float, default=0.01,
                       help="policy entropy's coefficient the loss function")
    args = parser.parse_args()
    if not args.seed:
        args.seed = int(time.time())

# TRY NOT TO MODIFY: setup the environment
env = gym.make(args.gym_id)
config = gym_microrts.types.Config(
    ai1_type="no-penalty",
    ai2_type="passive",
    map_path="maps/4x4/base4x4.xml",
    render=True,
    client_port=9898,
    microrts_path="E:/Go/src/github.com/vwxyzjn/201906051646.microrts"
)
if args.prod_mode:
    import wandb
    config.render = False
    config.microrts_path = "/root/microrts"
env.init(config)
random.seed(args.seed)
np.random.seed(args.seed)
torch.manual_seed(args.seed)
torch.backends.cudnn.deterministic = args.torch_deterministic
env.seed(args.seed)
input_shape, preprocess_obs_fn = preprocess_obs_space(env.observation_space)
output_shape, preprocess_ac_fn = preprocess_ac_space(env.action_space)

# TODO: initialize agent here:
class Policy(nn.Module):
    def __init__(self):
        super(Policy, self).__init__()
        self.fc1 = nn.Linear(input_shape, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, output_shape)

    def forward(self, x):
        x = preprocess_obs_fn(x)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x

class Value(nn.Module):
    def __init__(self):
        super(Value, self).__init__()
        self.fc1 = nn.Linear(input_shape, 64)
        self.fc2 = nn.Linear(64, 1)

    def forward(self, x):
        x = preprocess_obs_fn(x)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return x

pg = Policy()
vf = Value()
optimizer = optim.Adam(list(pg.parameters()) + list(vf.parameters()), lr=args.learning_rate)
loss_fn = nn.MSELoss()

# TRY NOT TO MODIFY: start the game
experiment_name = f"{time.strftime('%b%d_%H-%M-%S')}__{args.exp_name}__{args.seed}"
writer = SummaryWriter(f"runs/{experiment_name}")
writer.add_text('hyperparameters', "|param|value|\n|-|-|\n%s" % (
        '\n'.join([f"|{key}|{value}|" for key, value in vars(args).items()])))
if args.prod_mode:
    wandb.init(project="MicrortsRL", tensorboard=True, config=vars(args))
    writer = SummaryWriter(f"/tmp/{experiment_name}")
global_step = 0
while global_step < args.total_timesteps:
    next_obs = np.array(env.reset())
    actions = np.empty((args.episode_length,), dtype=object)
    rewards, dones = np.zeros((2, args.episode_length))
    obs = np.empty((args.episode_length,) + env.observation_space.shape)
    
    # TODO: put other storage logic here
    values = torch.zeros((args.episode_length))
    neglogprobs = torch.zeros((args.episode_length,))
    entropys = torch.zeros((args.episode_length,))
    
    # TRY NOT TO MODIFY: prepare the execution of the game.
    for step in range(args.episode_length):
        global_step += 1
        obs[step] = next_obs.copy()
        
        # TODO: put action logic here
        logits = pg.forward(obs[step])
        values[step] = vf.forward(obs[step])
        probs, actions[step], neglogprobs[step], entropys[step] = preprocess_ac_fn(logits)
        
        # TRY NOT TO MODIFY: execute the game and log data.
        next_obs, rewards[step], dones[step], _ = env.step(actions[step])
        next_obs = np.array(next_obs)
        if dones[step]:
            break
        
        if args.prod_mode and global_step % 20000 == 0:
            torch.save(pg.state_dict(), "/tmp/pg.pt")
            torch.save(vf.state_dict(), "/tmp/vf.pt")
            wandb.save("/tmp/pg.pt")
            wandb.save("/tmp/vf.pt")
    
    # TODO: training.
    # calculate the discounted rewards, or namely, returns
    returns = np.zeros_like(rewards)
    for t in reversed(range(rewards.shape[0]-1)):
        returns[t] = rewards[t] + args.gamma * returns[t+1] * (1-dones[t])
    # advantages are returns - baseline, value estimates in our case
    advantages = returns - values.detach().numpy()
    
    vf_loss = loss_fn(torch.Tensor(returns), torch.Tensor(values)) * args.vf_coef
    pg_loss = torch.Tensor(advantages) * neglogprobs
    loss = (pg_loss - entropys * args.ent_coef).mean() + vf_loss
    
    optimizer.zero_grad()
    loss.backward()
    nn.utils.clip_grad_norm_(list(pg.parameters()) + list(vf.parameters()), args.max_grad_norm)
    optimizer.step()

    # TRY NOT TO MODIFY: record rewards for plotting purposes
    writer.add_scalar("charts/episode_reward", rewards.sum(), global_step)
    writer.add_scalar("charts/global_step", global_step, global_step)
env.close()
writer.close()
