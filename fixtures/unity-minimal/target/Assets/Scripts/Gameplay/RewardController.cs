using System;
using UnityEngine;
using UnityEngine.Events;

namespace ChangeLens.Fixture
{
    public sealed class RewardController : MonoBehaviour
    {
        [SerializeField] private Wallet wallet;
        [SerializeField] private RewardPolicy rewardPolicy;
        [SerializeField] private UnityEvent<int> claimed;

        private void Awake()
        {
            wallet.ResetDaily();
        }

        public bool TryClaim(int amount)
        {
            if (amount <= 0)
            {
                return false;
            }

            if (wallet.IsLocked)
            {
                throw new InvalidOperationException("Wallet is locked.");
            }

            var credited = amount + rewardPolicy.CalculateBonus(amount);
            wallet.Credit(credited);
            claimed.Invoke(credited);
            SendMessage("RefreshHud", credited, SendMessageOptions.DontRequireReceiver);
            return true;
        }
    }
}

