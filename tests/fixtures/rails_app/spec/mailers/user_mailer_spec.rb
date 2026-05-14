describe UserMailer do
  it "renders welcome email" do
    expect(UserMailer.new.welcome_email(User.new("ada@example.com"))).to include("welcome")
  end
end
