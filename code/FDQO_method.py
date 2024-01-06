from __future__ import division
import warnings
import tensorflow.keras.backend as K
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Lambda, Input, Layer, Dense

from rl.core import Agent

from policy import EpsGreedyQPolicy
from rl.util import *

from fuzzy_controller import *
from multiset import *
from queue import Queue

def mean_q(y_true, y_pred):
    return K.mean(K.max(y_pred, axis=-1))
class AbstractDQNAgent(Agent):
    """Write me
    """
    def __init__(self, nb_actions, memory, gamma=.99, batch_size=32, nb_steps_warmup=1000,
                 train_interval=1, memory_interval=1, target_model_update=10000,
                 delta_range=None, delta_clip=np.inf, custom_model_objects={}, **kwargs):
        super(AbstractDQNAgent, self).__init__(**kwargs)

        # Soft vs hard target model updates.
        if target_model_update < 0:
            raise ValueError('`target_model_update` must be >= 0.')
        elif target_model_update >= 1:
            # Hard update every `target_model_update` steps.
            target_model_update = int(target_model_update)
        else:
            # Soft update with `(1 - target_model_update) * old + target_model_update * new`.
            target_model_update = float(target_model_update)

        if delta_range is not None:
            warnings.warn('`delta_range` is deprecated. Please use `delta_clip` instead, which takes a single scalar. For now we\'re falling back to `delta_range[1] = {}`'.format(delta_range[1]))
            delta_clip = delta_range[1]

        # Parameters.
        self.nb_actions = nb_actions
        self.gamma = gamma
        self.batch_size = batch_size
        self.nb_steps_warmup = nb_steps_warmup
        self.train_interval = train_interval
        self.memory_interval = memory_interval
        self.target_model_update = target_model_update
        self.delta_clip = delta_clip
        self.custom_model_objects = custom_model_objects
        # Related objects.
        self.memory = memory
        # State.
        self.compiled = False

    def process_state_batch(self, batch):
        batch = np.array(batch)
        if self.processor is None:
            return batch
        return self.processor.process_state_batch(batch)

    def compute_batch_q_values(self, state_batch):
        batch = self.process_state_batch(state_batch)
        q_values = self.model.predict_on_batch(batch)
        assert q_values.shape == (len(state_batch), self.nb_actions)
        return q_values

    def compute_q_values(self, state):
        q_values = self.compute_batch_q_values([state]).flatten()
        assert q_values.shape == (self.nb_actions,)
        return q_values

    def get_config(self):
        return {
            'nb_actions': self.nb_actions,
            'gamma': self.gamma,
            'batch_size': self.batch_size,
            'nb_steps_warmup': self.nb_steps_warmup,
            'train_interval': self.train_interval,
            'memory_interval': self.memory_interval,
            'target_model_update': self.target_model_update,
            'delta_clip': self.delta_clip,
            'memory': get_object_config(self.memory),
        }

# An implementation of the DQN agent as described in Mnih (2013) and Mnih (2015).
# http://arxiv.org/pdf/1312.5602.pdf
# http://arxiv.org/abs/1509.06461
class DQNAgent(AbstractDQNAgent):
    """
    # Arguments
        model__: A Keras model.
        policy__: A Keras-rl policy that are defined in [policy](https://github.com/keras-rl/keras-rl/blob/master/rl/policy.py).
        test_policy__: A Keras-rl policy.
        enable_double_dqn__: A boolean which enable target network as a second network proposed by van Hasselt et al. to decrease overfitting.
        enable_dueling_dqn__: A boolean which enable dueling architecture proposed by Mnih et al.
        dueling_type__: If `enable_dueling_dqn` is set to `True`, a type of dueling architecture must be chosen which calculate Q(s,a) from V(s) and A(s,a) differently. Note that `avg` is recommanded in the [paper](https://arxiv.org/abs/1511.06581).
            `avg`: Q(s,a;theta) = V(s;theta) + (A(s,a;theta)-Avg_a(A(s,a;theta)))
            `max`: Q(s,a;theta) = V(s;theta) + (A(s,a;theta)-max_a(A(s,a;theta)))
            `naive`: Q(s,a;theta) = V(s;theta) + A(s,a;theta)
    """
    def __init__(self, model, policy=None, test_policy=None, enable_double_dqn=False, enable_dueling_network=False,
                 dueling_type='avg', *args, **kwargs):
        
        super(DQNAgent, self).__init__(*args, **kwargs)

        # Validate (important) input.
        if list(model.output.shape) != list((None, self.nb_actions)):
            raise ValueError('Model output "{}" has invalid shape. DQN expects a model that has one dimension for each action, in this case {}.'.format(model.output, self.nb_actions))


        # Parameters.
        #
        self.files = open("kq.csv","w")
        self.fuzzy_logic = Fuzzy_Controller()
        self.enable_double_dqn = enable_double_dqn
        self.enable_dueling_network = enable_dueling_network
        self.dueling_type = dueling_type
        self.average_reward = 0
        self.t = 0
        self.sumreward = 0
        self.reward_capacity = 2000
        
        ## Hieu algo
        self.reward_capacity_needed = 1750
        self.multiset = Multiset()
        ##
        self.reward_queue = Queue(maxsize = self.reward_capacity)
        self.epsilon = 0.12
        self.k = 0.05
        self.threshold = 0.85
        # self.reward_queue2 = Queue(maxsize = 10000)
        # self.sumreward2 = 0
        # self.average_reward2 = 0
        # self.t2 = 0
        if self.enable_dueling_network:
            # get the second last layer of the model, abandon the last layer
            layer = model.layers[-2]
            nb_action = model.output.shape[-1]
            # layer y has a shape (nb_action+1,)
            # y[:,0] represents V(s;theta)
            # y[:,1:] represents A(s,a;theta)
            y = Dense(nb_action + 1, activation='linear')(layer.output)
            # caculate the Q(s,a;theta)
            # dueling_type == 'avg'
            # Q(s,a;theta) = V(s;theta) + (A(s,a;theta)-Avg_a(A(s,a;theta)))
            # dueling_type == 'max'
            # Q(s,a;theta) = V(s;theta) + (A(s,a;theta)-max_a(A(s,a;theta)))
            # dueling_type == 'naive'
            # Q(s,a;theta) = V(s;theta) + A(s,a;theta)
            if self.dueling_type == 'avg':
                outputlayer = Lambda(lambda a: K.expand_dims(a[:, 0], -1) + a[:, 1:] - K.mean(a[:, 1:], axis=1, keepdims=True), output_shape=(nb_action,))(y)
            elif self.dueling_type == 'max':
                outputlayer = Lambda(lambda a: K.expand_dims(a[:, 0], -1) + a[:, 1:] - K.max(a[:, 1:], axis=1, keepdims=True), output_shape=(nb_action,))(y)
            elif self.dueling_type == 'naive':
                outputlayer = Lambda(lambda a: K.expand_dims(a[:, 0], -1) + a[:, 1:], output_shape=(nb_action,))(y)
            else:
                assert False, "dueling_type must be one of {'avg','max','naive'}"

            model = Model(inputs=model.input, outputs=outputlayer)

        # Related objects.
        self.model = model
        if policy is None:
            policy = EpsGreedyQPolicy(0.0)
        if test_policy is None:
            test_policy = EpsGreedyQPolicy(0.0)
        self.policy = policy
        self.test_policy = test_policy

        # State.
        self.reset_states()

    def get_config(self):
        config = super(DQNAgent, self).get_config()
        config['enable_double_dqn'] = self.enable_double_dqn
        config['dueling_type'] = self.dueling_type
        config['enable_dueling_network'] = self.enable_dueling_network
        config['model'] = get_object_config(self.model)
        config['policy'] = get_object_config(self.policy)
        config['test_policy'] = get_object_config(self.test_policy)
        if self.compiled:
            config['target_model'] = get_object_config(self.target_model)
        return config

    def compile(self, optimizer, metrics=[]):
        metrics += [mean_q]  # register default metrics

        # We never train the target model, hence we can set the optimizer and loss arbitrarily.
        self.target_model = clone_model(self.model, self.custom_model_objects)
        self.target_model.compile(optimizer='sgd', loss='mse')
        self.model.compile(optimizer='sgd', loss='mse')

        # Compile model.
        if self.target_model_update < 1.:
            # We use the `AdditionalUpdatesOptimizer` to efficiently soft-update the target model.
            updates = get_soft_target_model_updates(self.target_model, self.model, self.target_model_update)
            optimizer = AdditionalUpdatesOptimizer(optimizer, updates)

        def clipped_masked_error(args):
            y_true, y_pred, mask = args
            loss = huber_loss(y_true, y_pred, self.delta_clip)
            loss *= mask  # apply element-wise mask
            return K.sum(loss, axis=-1)

        # Create trainable model. The problem is that we need to mask the output since we only
        # ever want to update the Q values for a certain action. The way we achieve this is by
        # using a custom Lambda layer that computes the loss. This gives us the necessary flexibility
        # to mask out certain parameters by passing in multiple inputs to the Lambda layer.
        y_pred = self.model.output
        y_true = Input(name='y_true', shape=(self.nb_actions,))
        mask = Input(name='mask', shape=(self.nb_actions,))
        loss_out = Lambda(clipped_masked_error, output_shape=(1,), name='loss')([y_true, y_pred, mask])
        ins = [self.model.input] if type(self.model.input) is not list else self.model.input
        trainable_model = Model(inputs=ins + [y_true, mask], outputs=[loss_out, y_pred])
        assert len(trainable_model.output_names) == 2
        combined_metrics = {trainable_model.output_names[1]: metrics}
        losses = [
            lambda y_true, y_pred: y_pred,  # loss is computed in Lambda layer
            lambda y_true, y_pred: K.zeros_like(y_pred),  # we only include this for the metrics
        ]
        trainable_model.compile(optimizer=optimizer, loss=losses, metrics=combined_metrics)
        self.trainable_model = trainable_model

        self.compiled = True

    def load_weights(self, filepath):
        self.model.load_weights(filepath)
        self.update_target_model_hard()

    def save_weights(self, filepath, overwrite=False):
        self.model.save_weights(filepath, overwrite=overwrite)

    def reset_states(self):
        self.recent_action = None
        self.recent_observation = None
        if self.compiled:
            self.model.reset_states()
            self.target_model.reset_states()

    def update_target_model_hard(self):
        self.target_model.set_weights(self.model.get_weights())

    def estimate_reward(self, action, observation ):
        time_delay = 0
        #logic block when computing node is bus node
        if action>0 and action<4:
            Rate_trans_req_data = (10*np.log2(1+46/(np.power(observation[(action-1)*3],4)*100))) / 8
            time_delay =  observation[11]/(1000*observation[2+(action-1)*3]) + max(observation[12]/(Rate_trans_req_data*1000),observation[1+(action-1)*3])

            #distance_response = self.readexcel(900+action-1,self.observation[1+(action-1)*3]+self.time)
            #Rate_trans_res_data = (10*np.log2(1+46/(np.power(distance_response,4)*100)))/8
            #time_delay = (self.observation[1+(action-1)*3]+self.queue[0][3]/(Rate_trans_res_data*1000))
            #self.node_computing.write("{},{},{},{},{},{}".format(action,self.observation[(action-1)*3],self.observation[9],self.observation[1],self.observation[4],self.observation[7]))
        
        #logic block when computing node is server
        if action == 0 :
            time_delay = observation[11]/(observation[10]*1000)
            #print(observation[11]/(1000*observation[2+(action-1)*3]))
            #print(time_delay)
            #import pdb;pdb.set_trace()
            #self.node_computing.write("{},{},{},{},{},{}".format(action,0,self.observation[9],self.observation[1],self.observation[4],self.observation[7]))
        
        #self.n_tasks_in_node[action] = self.n_tasks_in_node[action]+1
        reward = max(0,min((2*observation[13]-time_delay)/observation[13],1))
        return reward
    
    
    # FDQO forward
    # def forward(self, observation):
    #     # Select an action.
    #     state = self.memory.get_recent_state(observation)
    #     q_values = self.compute_q_values(state)
    #     if self.training:
    #         action = self.policy.select_action(q_values=q_values)
    #         if self.estimate_reward(action,observation)>0.8:
    #             action = action
    #             self.files.write("0\n")
    #             #print("A")
    #         else:
    #             action = self.fuzzy_logic.choose_action(observation)
    #             self.files.write("1\n")
    #     else:
    #         action = self.test_policy.select_action(q_values=q_values)

    #     # Book-keeping.
    #     self.recent_observation = observation
    #     self.recent_action = action

    #     return action
    
    
    # Db_FDQO forward
    # def forward(self, observation, step = 0, baseline = 0.5, eps = 0.0, r = 0):
    #     # Select an action.
        
    #     state = self.memory.get_recent_state(observation)
    #     q_values = self.compute_q_values(state)            
    #     if self.reward_capacity == 0:
    #         self.sumreward += r
    #         try:
    #             self.average_reward = self.sumreward / self.t
    #         except:
    #             pass
    #         self.t += 1
    #     else:
    #         #print(self.sumreward, self.reward_queue.qsize(), self.t)
    #         if self.reward_queue.full():
    #             self.sumreward -= self.reward_queue.get()
    #         self.reward_queue.put(r)
    #         self.sumreward += r
    #         try:
    #             self.average_reward = self.sumreward / self.t
    #         except:
    #             pass
    #         if (self.t < self.reward_capacity):
    #             self.t += 1
        
    #     if self.average_reward > baseline: # line 8-12
    #         epsilon = min(self.epsilon - self.k * (self.average_reward - baseline), self.epsilon)
    #         epsilon = max(epsilon, 0.01)
    #         if np.random.uniform() < epsilon:
    #             action = np.random.randint(0, 4)
    #             ext = False
    #         else:
    #             ext = True
    #             action = np.argmax(q_values)
    #     else: # algo 2
    #         action = self.policy.select_action(q_values=q_values)

    #         if self.estimate_reward(action, observation) > self.threshold:
    #             action = action
    #             ext = True
    #         else:
    #             action = self.fuzzy_logic.choose_action(observation)
    #             ext = False
    #     if ext:
    #         self.files.write("0\n")
    #     else:
    #         self.files.write("1\n")        
    #     # Book-keeping.
    #     self.recent_observation = observation
    #     self.recent_action = action
    #     return action
    
    
    
    # Hieu algo - DbpFDQO
    def forward(self, observation, step = 0, baseline = 0.2, eps = 0.0, r = 0):
        # Select an action.
        
        state = self.memory.get_recent_state(observation)
        q_values = self.compute_q_values(state)            
        
        if self.reward_queue.full():
            self.multiset.remove(self.reward_queue.get())
        self.reward_queue.put(r)
        self.multiset.insert(r)
        try:
            self.average_reward = self.multiset.sum_of_largest(self.t) / self.t
        except:
            pass
        if (self.t < self.reward_capacity_needed):
            self.t += 1
        
        if self.average_reward > baseline: # line 8-12
            epsilon = min(self.epsilon - self.k * (self.average_reward - baseline), self.epsilon)
            epsilon = max(epsilon, 0.01)
            if np.random.uniform() < epsilon:
                action = np.random.randint(0, 4)
                ext = False
            else:
                ext = True
                action = np.argmax(q_values)
        else: # algo 2
            action = self.policy.select_action(q_values=q_values)

            if self.estimate_reward(action, observation) > self.threshold:
                action = action
                ext = True
            else:
                action = self.fuzzy_logic.choose_action(observation)
                ext = False

        if ext:
            self.files.write("0\n")
        else:
            self.files.write("1\n")        

        # Book-keeping.
        self.recent_observation = observation
        self.recent_action = action

        return action

    def backward(self, reward, terminal):
        # Store most recent experience in memory.
        if self.step % self.memory_interval == 0:
            self.memory.append(self.recent_observation, self.recent_action, reward, terminal,
                               training=self.training)

        metrics = [np.nan for _ in self.metrics_names]
        if not self.training:
            # We're done here. No need to update the experience memory since we only use the working
            # memory to obtain the state over the most recent observations.
            return metrics

        # Train the network on a single stochastic batch.
        if self.step > self.nb_steps_warmup and self.step % self.train_interval == 0:
            experiences = self.memory.sample(self.batch_size)
            assert len(experiences) == self.batch_size

            # Start by extracting the necessary parameters (we use a vectorized implementation).
            state0_batch = []
            reward_batch = []
            action_batch = []
            terminal1_batch = []
            state1_batch = []
            for e in experiences:
                state0_batch.append(e.state0)
                state1_batch.append(e.state1)
                reward_batch.append(e.reward)
                action_batch.append(e.action)
                terminal1_batch.append(0. if e.terminal1 else 1.)

            # Prepare and validate parameters.
            state0_batch = self.process_state_batch(state0_batch)
            state1_batch = self.process_state_batch(state1_batch)
            terminal1_batch = np.array(terminal1_batch)
            reward_batch = np.array(reward_batch)
            assert reward_batch.shape == (self.batch_size,)
            assert terminal1_batch.shape == reward_batch.shape
            assert len(action_batch) == len(reward_batch)

            # Compute Q values for mini-batch update.
            if self.enable_double_dqn:
                # According to the paper "Deep Reinforcement Learning with Double Q-learning"
                # (van Hasselt et al., 2015), in Double DQN, the online network predicts the actions
                # while the target network is used to estimate the Q value.
                q_values = self.model.predict_on_batch(state1_batch)
                assert q_values.shape == (self.batch_size, self.nb_actions)
                actions = np.argmax(q_values, axis=1)
                assert actions.shape == (self.batch_size,)

                # Now, estimate Q values using the target network but select the values with the
                # highest Q value wrt to the online model (as computed above).
                target_q_values = self.target_model.predict_on_batch(state1_batch)
                assert target_q_values.shape == (self.batch_size, self.nb_actions)
                q_batch = target_q_values[range(self.batch_size), actions]
            else:
                # Compute the q_values given state1, and extract the maximum for each sample in the batch.
                # We perform this prediction on the target_model instead of the model for reasons
                # outlined in Mnih (2015). In short: it makes the algorithm more stable.
                target_q_values = self.target_model.predict_on_batch(state1_batch)
                assert target_q_values.shape == (self.batch_size, self.nb_actions)
                q_batch = np.max(target_q_values, axis=1).flatten()
            assert q_batch.shape == (self.batch_size,)

            targets = np.zeros((self.batch_size, self.nb_actions))
            dummy_targets = np.zeros((self.batch_size,))
            masks = np.zeros((self.batch_size, self.nb_actions))

            # Compute r_t + gamma * max_a Q(s_t+1, a) and update the target targets accordingly,
            # but only for the affected output units (as given by action_batch).
            discounted_reward_batch = self.gamma * q_batch
            # Set discounted reward to zero for all states that were terminal.
            discounted_reward_batch *= terminal1_batch
            assert discounted_reward_batch.shape == reward_batch.shape
            Rs = reward_batch + discounted_reward_batch
            for idx, (target, mask, R, action) in enumerate(zip(targets, masks, Rs, action_batch)):
                target[action] = R  # update action with estimated accumulated reward
                dummy_targets[idx] = R
                mask[action] = 1.  # enable loss for this specific action
            targets = np.array(targets).astype('float32')
            masks = np.array(masks).astype('float32')

            # Finally, perform a single update on the entire batch. We use a dummy target since
            # the actual loss is computed in a Lambda layer that needs more complex input. However,
            # it is still useful to know the actual target to compute metrics properly.
            ins = [state0_batch] if type(self.model.input) is not list else state0_batch
            metrics = self.trainable_model.train_on_batch(ins + [targets, masks], [dummy_targets, targets])
            metrics = [metric for idx, metric in enumerate(metrics) if idx not in (1, 2)]  # throw away individual losses
            metrics += self.policy.metrics
            if self.processor is not None:
                metrics += self.processor.metrics

        if self.target_model_update >= 1 and self.step % self.target_model_update == 0:
            self.update_target_model_hard()

        return metrics

    @property
    def layers(self):
        return self.model.layers[:]

    @property
    def metrics_names(self):
        # Throw away individual losses and replace output name since this is hidden from the user.
        assert len(self.trainable_model.output_names) == 2
        dummy_output_name = self.trainable_model.output_names[1]
        model_metrics = [name for idx, name in enumerate(self.trainable_model.metrics_names) if idx not in (1, 2)]
        model_metrics = [name.replace(dummy_output_name + '_', '') for name in model_metrics]

        names = model_metrics + self.policy.metrics_names[:]
        if self.processor is not None:
            names += self.processor.metrics_names[:]
        return names

    @property
    def policy(self):
        return self.__policy

    @policy.setter
    def policy(self, policy):
        self.__policy = policy
        self.__policy._set_agent(self)

    @property
    def test_policy(self):
        return self.__test_policy

    @test_policy.setter
    def test_policy(self, policy):
        self.__test_policy = policy
        self.__test_policy._set_agent(self)