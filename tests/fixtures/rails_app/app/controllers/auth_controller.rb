class AuthController
  def register(user)
    EmailJob.new.perform(user)
  end
end
