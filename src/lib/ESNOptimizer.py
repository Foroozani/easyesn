#from numpy import *

class Optimizer:

    def __init__(self, backend):
        self.backend = backend

    # f`(X)
    def activationDerivation(self, X):
        return 4 / (2 + self.backend.exp(2 * X) + self.backend.exp(-2 * X))

    # del x / del alpha
    def derivationForLeakingRate(self, reservoir, oldDerivative, u, x):
        a = reservoir.leakingRate
        X = reservoir.X(x, u)
        return (1-a) * oldDerivative - x + reservoir.f(X) + a * self.activationDerivation(X) * self.backend.dot(reservoir.W, oldDerivative )

    # del x / del rho
    def derivationForSpectralRadius(self, reservoir, W_uniform, oldDerivative, u, x):
        a = reservoir.leakingRate
        X = reservoir.X(x, u)
        return (1-a) * oldDerivative + a * self.activationDerivation(X) * ( self.backend.dot(reservoir.W, oldDerivative) + self.backend.dot(W_uniform, x) )

    # del x / del s_in
    def derivationForInputScaling(self, reservoir, W_in_uniform, oldDerivative, u, x):
        a = reservoir.leakingRate
        X = reservoir.X(x, u)
        u = self.backend.vstack((1,u))
        return (1-a)  * oldDerivative + a * self.activationDerivation(X) * ( self.backend.dot(reservoir.W, oldDerivative) + self.backend.dot(W_in_uniform, u) )

    # del W_out / del beta
    def derivationForPenalty(self, reservoir, Y, X, penalty):
        X_T = X.T
        term2 = self.backend.linalg.inv( self.backend.dot( X, X_T ) + penalty * self.backend.eye(1 + reservoir.input_dim + reservoir.size) )
        return - self.backend.dot( self.backend.dot( Y, X_T ), self.backend.dot( term2, term2 ) )

    # del W_out / del (alpha, rho or s_in)
    def derivationWoutForP(self, reservoir, Y, X, XPrime, penalty):
        X_T = X.T
        XPrime_T = XPrime.T

        # A = dot(X,X_T) + penalty*eye(1 + self.target_dim + self.size)
        # APrime = dot( XPrime, X_T) + dot( X, XPrime_T )
        # APrime_T = APrime.T
        # InvA = linalg.inv(A)
        # InvA_T = InvA.T
        #
        # term1 = dot(XPrime_T, InvA)
        #
        # term21 = -dot( InvA, dot( APrime, InvA ) )
        # term22 = dot( dot( dot( InvA, InvA_T), APrime_T), eye(1 + self.target_dim + self.size) - dot( A, InvA ) )
        # term23 = dot( dot( eye(1 + self.target_dim + self.size) - dot( InvA, A ), APrime_T), dot( InvA_T, InvA) )
        # term2 = dot( X_T, term21 + term22 + term23 )
        #
        # return dot( Y, term1 + term2)

        term1 = self.backend.linalg.inv(self.backend.dot(X,X_T) + penalty*self.backend.eye(1 + reservoir.input_dim + reservoir.size))
        term2 = self.backend.dot( XPrime, X_T) + self.backend.dot( X, XPrime_T )

        return self.backend.dot( Y, self.backend.dot( XPrime_T, term1 ) - self.backend.dot( self.backend.dot( self.backend.dot( X_T, term1 ), term2 ), term1 ) )


    ####################################################################################################################################################


    def optimizeParameterForTrainError(self, reservoir, inputs, targets, trainLength, learningRate=0.0001, epochs=1, penalty=0.1, errorEvaluationLength=500):
        # initializations of arrays:
        Ytarget = targets[None, reservoir.transientTime:trainLength]

        # initializations for plotting parameter and losses at the end
        inputScalings = list()
        leakingRates = list()
        spectralRadiuses = list()
        fitLosses = list()
        evaLosses = list()

        # initializations for arrays which collect all the gradients of the error of the single time steps, which get add at the end
        srGradients = self.backend.zeros(trainLength - reservoir.transientTime)
        lrGradients = self.backend.zeros(trainLength - reservoir.transientTime)
        isGradients = self.backend.zeros(trainLength - reservoir.transientTime)

        # collecting the single derivatives  - > this is the derivation of design matrix when filled
        srGradientsMatrix = self.backend.zeros((reservoir.size + reservoir.input_dim + 1, trainLength - reservoir.transientTime))
        lrGradientsMatrix = self.backend.zeros((reservoir.size + reservoir.input_dim + 1, trainLength - reservoir.transientTime))
        isGradientsMatrix = self.backend.zeros((reservoir.size + reservoir.input_dim + 1, trainLength - reservoir.transientTime))

        # initialize fallback Parameter
        oldSR = reservoir.spectralRadius
        oldLR = self.leakingRate
        oldIS = reservoir.inputScaling

        # initialize self.designMatrix and self.W_out
        _, oldLoss, = reservoir.fit(inputs, targets, trainLength, penalty=penalty, errorEvaluationLength=1)

        # Calculate uniform matrices
        W_uniform = reservoir.W_uniform
        W_in_uniform = reservoir.W_in_uniform

        for epoch in range(epochs):
            print("###################### Start epoch: " + str(epoch) + " ##########################")
            # initialize del x / del (rho, alpha, s_in) and reservoir state itself
            derivationSpectralRadius = self.backend.zeros((reservoir.size, 1))
            derivationLeakingRate = self.backend.zeros((reservoir.size, 1))
            derivationInputScaling = self.backend.zeros((reservoir.size, 1))
            # initialize the neuron states new
            x = self.backend.zeros((reservoir.size, 1))
            # go thorugh the train length (e.g. the time, on which W_out gets calculated)
            for t in range(trainLength):
                u = inputs[t].reshape(-1, 1)
                oldx = x
                x = reservoir.updateNeuronState(x, u)
                # calculate the del /x del (rho, alpha, s_in)
                derivationSpectralRadius = self.derivationForSpectralRadius(reservoir, W_uniform, derivationSpectralRadius, u, oldx)
                derivationLeakingRate = self.derivationForLeakingRate(reservoir, derivationLeakingRate, u, oldx)
                derivationInputScaling = self.derivationForInputScaling(reservoir, W_in_uniform, derivationInputScaling, u, oldx)
                if t >= reservoir.transientTime:
                    # concatenate with zeros (for the derivatives of the input and the 1, which are always 0)
                    derivationConcatinationSpectralRadius = self.backend.concatenate(
                        (self.backend.zeros(reservoir.input_dim + 1), derivationSpectralRadius[:, 0]), axis=0)
                    derivationConcatinationLeakingRate = self.backend.concatenate(
                        (self.backend.zeros(reservoir.input_dim + 1), derivationLeakingRate[:, 0]), axis=0)
                    derivationConcatinationInputScaling = self.backend.concatenate(
                        (self.backend.zeros(reservoir.input_dim + 1), derivationInputScaling[:, 0]), axis=0)
                    # add to matrix
                    srGradientsMatrix[:, t - reservoir.transientTime] = derivationConcatinationSpectralRadius
                    lrGradientsMatrix[:, t - reservoir.transientTime] = derivationConcatinationLeakingRate
                    isGradientsMatrix[:, t - reservoir.transientTime] = derivationConcatinationInputScaling
            # calculate del W_out / del (rho, alpha, s_in) based on the designMatrix and the derivative of the designMatrix we just calculated
            WoutPrimeSR = self.derivationWoutForP(reservoir, Ytarget, reservoir.designMatrix, srGradientsMatrix, penalty)
            WoutPrimeLR = self.derivationWoutForP(reservoir, Ytarget, reservoir.designMatrix, lrGradientsMatrix, penalty)
            WoutPrimeIS = self.derivationWoutForP(reservoir, Ytarget, reservoir.designMatrix, isGradientsMatrix, penalty)
            # reinitialize the states
            x = self.backend.zeros((reservoir.size, 1))
            # go through the train time again, and this time, calculate del error / del (rho, alpha, s_in) based on del W_out and the single derivatives
            for t in range(trainLength):
                u = inputs[t].reshape(-1, 1)
                x = reservoir.updateNeuronState(x, u)
                if t >= reservoir.transientTime:
                    # calculate error at given time step
                    error = (targets[t] - reservoir.readOut(u, x)).T
                    # calculate gradients
                    gradientSR = self.backend.dot(-error, self.backend.dot(WoutPrimeSR, self.backend.vstack((1, u, x))[:, 0]) + self.backend.dot(reservoir.W_out, srGradientsMatrix[:, t - reservoir.transientTime]))
                    srGradients[t - reservoir.transientTime] = gradientSR
                    gradientLR = self.backend.dot(-error, self.backend.dot(WoutPrimeLR, self.backend.vstack((1, u, x))[:, 0]) + self.backend.dot(reservoir.W_out, lrGradientsMatrix[:, t - reservoir.transientTime]))
                    lrGradients[t - reservoir.transientTime] = gradientLR
                    gradientIS = self.backend.dot(-error, self.backend.dot(WoutPrimeIS, self.backend.vstack((1, u, x))[:, 0]) + self.backend.dot(reservoir.W_out, isGradientsMatrix[:, t - reservoir.transientTime]))
                    isGradients[t - reservoir.transientTime] = gradientIS
            # sum up the gradients del error / del (rho, alpha, s_in) to get final gradient
            gradientSR = sum(srGradients)
            gradientLR = sum(lrGradients)
            gradientIS = sum(isGradients)
            # normalize gradients to length 1
            gradientVectorLength = self.backend.sqrt(gradientSR ** 2 + gradientLR ** 2 + gradientIS ** 2)
            # gradientVectorLength = sqrt(gradientSR ** 2 + gradientLR ** 2)
            # gradientVectorLength = sqrt(gradientSR ** 2)
            gradientSR /= gradientVectorLength
            gradientLR /= gradientVectorLength
            gradientIS /= gradientVectorLength
            # update spectral radius
            reservoir.tuneSpectralRadius(reservoir.spectralRadius - learningRate * gradientSR)
            # update leaking rate
            reservoir.leakingRate = reservoir.leakingRate - learningRate * gradientLR
            # update input scaling
            reservoir.tuneInputScaling(reservoir.inputScaling - learningRate * gradientIS)
            # calculate the errors and update the self.designMatrix and the W_out
            evaLoss, fitLoss = reservoir.fit(inputs, targets, trainLength, penalty=penalty,
                                        errorEvaluationLength=errorEvaluationLength)
            if fitLoss > oldLoss:
                reservoir.tuneSpectralRadius(oldSR)
                reservoir.leakingRate = oldLR
                reservoir.tuneInputScaling(oldIS)
                learningRate = learningRate / 2
            else:
                oldSR = reservoir.spectralRadius
                oldLR = reservoir.leakingRate
                oldIS = reservoir.inputScaling
                oldLoss = fitLoss
                spectralRadiuses.append(reservoir.spectralRadius)
                leakingRates.append(reservoir.leakingRate)
                inputScalings.append(reservoir.inputScaling)
                fitLosses.append(fitLoss)
                evaLosses.append(evaLoss)
        evaLoss = evaLosses[-1]
        fitLoss = fitLosses[-1]
        return (evaLoss, fitLoss, evaLosses, fitLosses, inputScalings, leakingRates, spectralRadiuses)


    def optimizeParameterForEvaluationError(self, reservoir, inputs, targets, trainLength, optimizationLength, learningRate=0.0001, epochs=1, penalty=0.1):

        # initializations of arrays:
        Ytarget = targets[None, reservoir.transientTime:trainLength]

        # initializations for plotting parameter and losses at the end
        inputScalings = list()
        leakingRates = list()
        spectralRadiuses = list()
        fitLosses = list()
        evaLosses = list()

        # initializations for arrays which collect all the gradients of the error of the single time steps, which get add at the end
        srGradients = self.backend.zeros(optimizationLength)
        lrGradients = self.backend.zeros(optimizationLength)
        isGradients = self.backend.zeros(optimizationLength)

        # collecting the single derivatives  - > this is the derivation of design matrix when filled
        srGradientsMatrix = self.backend.zeros((reservoir.size + reservoir.input_dim + 1, trainLength - reservoir.transientTime))
        lrGradientsMatrix = self.backend.zeros((reservoir.size + reservoir.input_dim + 1, trainLength - reservoir.transientTime))
        isGradientsMatrix = self.backend.zeros((reservoir.size + reservoir.input_dim + 1, trainLength - reservoir.transientTime))

        # initialize variables for the "when the error goes up, go back and divide learning rate by 2" mechanism
        oldSR = reservoir.spectralRadius
        oldLR = reservoir.leakingRate
        oldIS = reservoir.inputScaling

        # initialize self.designMatrix and self.W_out
        oldLoss, _, = reservoir.fit(inputs, targets, trainLength, penalty=penalty,
                               errorEvaluationLength=optimizationLength)

        # Calculate uniform matrices
        W_uniform = reservoir.W_uniform
        W_in_uniform = reservoir.W_in_uniform

        for epoch in range(epochs):
            print("###################### Start epoch: " + str(epoch) + " ##########################")
            # initialize del x / del (rho, alpha, s_in) and reservoir state itself
            derivationSpectralRadius = self.backend.zeros((reservoir.size, 1))
            derivationLeakingRate = self.backend.zeros((reservoir.size, 1))
            derivationInputScaling = self.backend.zeros((reservoir.size, 1))
            x = self.backend.zeros((reservoir.size, 1))
            # go thorugh the train length (e.g. the time, on which W_out gets calculated)
            for t in range(trainLength):
                u = inputs[t].reshape(-1, 1)
                oldx = x
                x = reservoir.updateNeuronState(x, u)
                # calculate the del x/ del (rho, alpha, s_in)
                derivationSpectralRadius = self.derivationForSpectralRadius(reservoir, W_uniform, derivationSpectralRadius, u, oldx)
                derivationLeakingRate = self.derivationForLeakingRate(reservoir, derivationLeakingRate, u, oldx)
                derivationInputScaling = self.derivationForInputScaling(reservoir, W_in_uniform, derivationInputScaling, u, oldx)
                if t >= reservoir.transientTime:
                    # concatenate with zeros (for the derivatives of the input and the 1, which are always 0)
                    srGradientsMatrix[:, t - reservoir.transientTime] = self.backend.concatenate(
                        (self.backend.zeros(reservoir.input_dim + 1), derivationSpectralRadius[:, 0]), axis=0)
                    lrGradientsMatrix[:, t - reservoir.transientTime] = self.backend.concatenate(
                        (self.backend.zeros(reservoir.input_dim + 1), derivationLeakingRate[:, 0]), axis=0)
                    isGradientsMatrix[:, t - reservoir.transientTime] = self.backend.concatenate(
                        (self.backend.zeros(reservoir.input_dim + 1), derivationInputScaling[:, 0]), axis=0)
            # add to matrix
            WoutPrimeSR = self.derivationWoutForP(reservoir, Ytarget, reservoir.designMatrix, srGradientsMatrix, penalty)
            WoutPrimeLR = self.derivationWoutForP(reservoir, Ytarget, reservoir.designMatrix, lrGradientsMatrix, penalty)
            WoutPrimeIS = self.derivationWoutForP(reservoir, Ytarget, reservoir.designMatrix, isGradientsMatrix, penalty)
            # this time go through validation length
            for t in range(optimizationLength):
                u = inputs[t + trainLength].reshape(-1, 1)
                oldx = x
                x = reservoir.updateNeuronState(x, u)
                # calculate error at given time step
                error = (targets[t + trainLength] - reservoir.readOut(u, x)).T
                # calculate del x / del (rho, alpha, s_in)
                derivationSpectralRadius = self.derivationForSpectralRadius(reservoir, W_uniform, derivationSpectralRadius, u, oldx)
                derivationLeakingRate = self.derivationForLeakingRate(reservoir, derivationLeakingRate, u, oldx)
                derivationInputScaling = self.derivationForInputScaling(reservoir, W_in_uniform, derivationInputScaling, u, oldx)
                # concatenate derivations with 0
                derivationConcatinationSpectralRadius = self.backend.concatenate(
                    (self.backend.zeros(reservoir.input_dim + 1), derivationSpectralRadius[:, 0]), axis=0)
                derivationConcatinationLeakingRate = self.backend.concatenate(
                    (self.backend.zeros(reservoir.input_dim + 1), derivationLeakingRate[:, 0]), axis=0)
                derivationConcatinationInputScaling = self.backend.concatenate(
                    (self.backend.zeros(reservoir.input_dim + 1), derivationInputScaling[:, 0]), axis=0)
                # calculate gradients
                gradientSR = self.backend.dot(-error, self.backend.dot(reservoir.W_out, derivationConcatinationSpectralRadius) + self.backend.dot(WoutPrimeSR,
                                                                                                                                self.backend.vstack((1, u,
                                                                                                              x))[:,
                                                                                                      0]))
                srGradients[t] = gradientSR
                gradientLR = self.backend.dot(-error, self.backend.dot(reservoir.W_out, derivationConcatinationLeakingRate) + self.backend.dot(WoutPrimeLR,
                                                                                                                self.backend.vstack(
                                                                                                       (1, u, x))[:,
                                                                                                   0]))
                lrGradients[t] = gradientLR
                gradientIS = self.backend.dot(-error, self.backend.dot(reservoir.W_out, derivationConcatinationInputScaling) + self.backend.dot(WoutPrimeIS,
                                                                                                                                           self.backend.vstack(
                                                                                                        (1, u, x))[
                                                                                                    :, 0]))
                isGradients[t] = gradientIS
            # sum up the gradients del error / del (rho, alpha, s_in) to get final gradient
            gradientSR = sum(srGradients)
            gradientLR = sum(lrGradients)
            gradientIS = sum(isGradients)
            # normalize length of gradient to 1
            gradientVectorLength = self.backend.sqrt(gradientSR ** 2 + gradientLR ** 2 + gradientIS ** 2)
            # gradientVectorLength = sqrt(gradientIS ** 2 + gradientLR ** 2 )
            gradientSR /= gradientVectorLength
            gradientLR /= gradientVectorLength
            gradientIS /= gradientVectorLength
            # update spectral radius
            reservoir.tuneSpectralRadius(reservoir.spectralRadius - learningRate * gradientSR)
            # update leaking rate
            self.leakingRate = self.leakingRate - learningRate * gradientLR
            # update input scaling
            reservoir.tuneInputScaling(reservoir.inputScaling - learningRate * gradientIS)
            # calculate the errors and update the self.designMatrix and the W_out
            evaLoss, fitLoss = reservoir.fit(inputs, targets, trainLength, penalty=penalty,
                                        errorEvaluationLength=optimizationLength)
            # this is the "when the error goes up, go back and divide learning rate by 2" mechanism
            if evaLoss > oldLoss:
                reservoir.tuneSpectralRadius(oldSR)
                reservoir.leakingRate = oldLR
                reservoir.tuneInputScaling(oldIS)
                learningRate = learningRate / 2
            else:
                oldSR = reservoir.spectralRadius
                oldLR = reservoir.leakingRate
                oldIS = reservoir.inputScaling
                oldLoss = evaLoss
                spectralRadiuses.append(reservoir.spectralRadius)
                leakingRates.append(reservoir.leakingRate)
                inputScalings.append(reservoir.inputScaling)
                fitLosses.append(fitLoss)
                evaLosses.append(evaLoss)
        evaLoss = evaLosses[-1]
        fitLoss = fitLosses[-1]
        return (evaLoss, fitLoss, evaLosses, fitLosses, inputScalings, leakingRates, spectralRadiuses)


    def optimizePenaltyForEvaluationError(self, reservoir, inputs, targets, trainLength, optimizationLength, learningRate=0.0001, epochs=1, penalty=0.1):

        Ytarget = targets[None, reservoir.transientTime:trainLength]
        penalty = penalty

        fitLosses = list()
        evaLosses = list()
        penalties = list()

        penaltyDerivatives = self.backend.zeros(optimizationLength)
        oldPenalty = penalty

        oldLoss, fitLoss = reservoir.fit(inputs, targets, trainLength, penalty=penalty,
                                    errorEvaluationLength=optimizationLength)

        evaluationEchoFunction = self.backend.zeros((1 + reservoir.size + reservoir.input_dim, optimizationLength))
        u = inputs[trainLength]
        x = reservoir.x

        for t in range(optimizationLength):
            x = reservoir.updateNeuronState(x, u)
            u = inputs[trainLength + t].reshape(-1, 1)
            evaluationEchoFunction[:, t] = self.backend.vstack((1, u, x)).squeeze()
            # u = predictionPoint

        for epoch in range(epochs):
            print("###################### Start epoch: " + str(epoch) + " ##########################")
            penaltyDerivative = self.derivationForPenalty(reservoir, Ytarget, reservoir.designMatrix, penalty)
            for t in range(optimizationLength):
                predictionPoint = self.backend.dot(reservoir.W_out, evaluationEchoFunction[:, t].reshape(-1, 1))
                error = (targets[trainLength + t] - predictionPoint).T
                penaltyDerivatives[t] = - self.backend.dot(self.backend.dot(error, penaltyDerivative), self.backend.vstack((1, u, x))[:, 0])
                u = inputs[trainLength + t].reshape(-1, 1)
                # u = predictionPoint
            penaltyGradient = sum(penaltyDerivatives)
            penaltyGradient /= self.backend.sqrt(penaltyGradient ** 2)
            penalty = penalty - learningRate * penaltyGradient
            evaLoss, fitLoss = reservoir.fit(inputs, targets, trainLength, penalty=penalty,
                                        errorEvaluationLength=optimizationLength)
            # this is the "when the error goes up, go back and divide learning rate by 2" mechanism
            if evaLoss > oldLoss:
                penalty = oldPenalty
                learningRate = learningRate / 2
            else:
                oldPenalty = penalty
                oldLoss = evaLoss
                fitLosses.append(fitLoss)
                evaLosses.append(evaLoss)
                penalties.append(penalty)
        return (evaLoss, fitLoss, evaLosses, fitLosses, penalties)