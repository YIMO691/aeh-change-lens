using System;
using UnityEngine;
using UnityEngine.Events;

namespace ChangeLens.Fixture
{
    public sealed class RewardController : MonoBehaviour
    {
        [SerializeField] private Wallet wallet;
        [SerializeField] private UnityEvent<int> claimed;

        private void Start()
        {
            wallet.ResetDaily();
        }

        public void Claim(int amount)
        {
            if (amount <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(amount));
            }

            var credited = amount + CalculateBonus(amount);
            wallet.Credit(credited);
            claimed.Invoke(credited);
            LegacyAudit(credited);
        }

        private static int CalculateBonus(int amount)
        {
            return amount >= 100 ? 10 : 0;
        }

        private static void LegacyAudit(int amount)
        {
            Debug.Log($"Legacy reward: {amount}");
        }
    }
}

